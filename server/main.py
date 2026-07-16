"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    SYLLABUS-TO-CALENDAR API (BACKEND)                        ║
║                           server/main.py                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

PURPOSE & ROLE IN PIPELINE:
──────────────────────────
This is the ORCHESTRATOR/COORDINATOR of the entire system. It's the central hub
that receives requests from the frontend (index.html), coordinates the processing
pipeline, and returns results.

Think of it as the TRAFFIC CONTROLLER that:
1. Receives file uploads from frontend
2. Routes files to text extraction layer
3. Sends extracted text to AI layer (Gemini)
4. Passes AI response to validation layer
5. Converts final data to calendar format
6. Returns results back to frontend

PROCESS PIPELINE (What happens when a user uploads a file):
─────────────────────────────────────────────────────────
User uploads PDF
    ↓
POST /process endpoint receives file
    ↓
Step 1: Validate file type, size, content
    ↓
Step 2: Extract text from PDF/TXT/MD
    ↓
Step 3: Send extracted text to Google Gemini AI
    ↓
Step 4: Get JSON events from Gemini
    ↓
Step 5: Validate & normalize the JSON response
    ↓
Step 6: Return clean events to frontend
    ↓
Frontend displays events to user

DEPENDENCIES:
─────────────
External Libraries:
  - fastapi (v0.109.0): Web framework for building HTTP APIs
  - uvicorn (v0.27.0): ASGI server that runs the FastAPI app
  - python-dotenv: Loads environment variables from .env file
  
Internal Modules:
  - src.ingest.file_ingestor: Extracts text from PDF/TXT/MD files
  - src.ai.gemini_pipeline_controller: Calls Google Gemini API
  - src.validation.string_validator: Validates & normalizes AI response
  - src.export.icalendar_factory: Converts events to RFC 5545 format

Configuration Files:
  - .env: Stores GOOGLE_API_KEY (loaded at startup)

ALGORITHMS USED:
────────────────
1. FILE VALIDATION ALGORITHM:
   - Check file extension against SUPPORTED_TYPES
   - Check file size doesn't exceed MAX_FILE_SIZE_MB
   - Check file is not empty
   - Exception-based error handling for quick failure

2. ASYNC/TIMEOUT ALGORITHM:
   - Uses asyncio.wait_for() to set 45-second timeout on Gemini API calls
   - Prevents server from hanging if Gemini is slow/overloaded
   - Non-blocking I/O allows server to handle multiple requests

3. ERROR MAPPING ALGORITHM:
   - Catches specific error types
   - Translates to appropriate HTTP status codes
   - Returns user-friendly error messages

HTTP ENDPOINTS:
───────────────
GET  /health    → {"status": "ok"}                       [Health check]
POST /process   → text/event-stream of phase/error/result events [Main processing, streamed]
POST /download  → binary .ics file                       [Calendar export]

Run locally:
    uvicorn server.main:app --reload --port 8000

Environment variables required:
    GOOGLE_API_KEY (from Google Cloud Console)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status

# Load environment variables from .env file at startup
# This makes GOOGLE_API_KEY available via os.getenv()
load_dotenv()

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)

import asyncio
import json
import secrets
import time
from collections import deque

from starlette.middleware.sessions import SessionMiddleware

# Import the four layers of the processing pipeline
from src.ingest.file_ingestor import extract_text_from_bytes
from src.ai.gemini_pipeline_controller import GeminiPipelineController, DEFAULT_MODEL
from src.validation.string_validator import sanitize_model_output
from src.export.icalendar_factory import build_ics
from src.calendar_push import google_calendar_client as gcal
from src.calendar_push import microsoft_calendar_client as mscal

"""
INITIALIZATION SECTION - Configuration & Setup
───────────────────────────────────────────────
This section sets up the FastAPI application with necessary configuration
and imports all the pipeline components.
"""

# Create FastAPI application instance
# This object handles all HTTP routing and request/response processing
app = FastAPI(title="Syllabus-to-Calendar API", version="1.0.0")

# CORS (Cross-Origin Resource Sharing) Middleware
# ─────────────────────────────────────────────────
# The frontend is served by this same app (see the "/" route below), so in
# practice almost every request is same-origin and doesn't need CORS at all.
# This stays as a defense-in-depth backstop, restricted to a single
# configurable origin rather than a wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("ALLOWED_ORIGIN", "http://localhost:8000")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Session cookie middleware -- gives each visitor a signed, opaque session
# id so concurrent users' Google Calendar credentials never collide (see
# src/calendar_push/google_calendar_client.py's per-session _sessions dict).
# No database involved: the cookie just carries an id, the actual
# credentials live in that module's in-memory store, keyed by this id.
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET_KEY", "dev-only-insecure-key-change-in-production"),
    same_site="lax",
    https_only=os.getenv("SESSION_HTTPS_ONLY", "false").lower() == "true",
)


def _get_session_id(request: Request) -> str:
    """Return this visitor's opaque session id, creating one on first use."""
    sid = request.session.get("sid")
    if not sid:
        sid = secrets.token_urlsafe(32)
        request.session["sid"] = sid
    return sid


# ---------------------------------------------------------------------------
# Gemini rate limiting -- protects the one shared API key when many public
# visitors upload concurrently. No external queue/Redis: an in-process
# semaphore caps concurrent calls, and a sliding 60-second window caps total
# calls per minute (the free tier's own limit). Not a strict FIFO queue --
# a simple waiting counter is enough for honest user-facing messaging.
# ---------------------------------------------------------------------------

_GEMINI_MAX_CONCURRENT = int(os.getenv("GEMINI_MAX_CONCURRENT", "3"))
_GEMINI_MAX_PER_MINUTE = int(os.getenv("GEMINI_MAX_PER_MINUTE", "15"))

_gemini_semaphore = asyncio.Semaphore(_GEMINI_MAX_CONCURRENT)
_gemini_call_times: deque[float] = deque()
_gemini_rate_lock = asyncio.Lock()
_gemini_waiting_count = 0


async def _throttle_gemini():
    """Async generator: yields a status string each time a wait is needed,
    then returns once a concurrency slot is held and the sliding per-minute
    window has room. Caller MUST call _release_gemini_slot() (in a finally
    block) once its Gemini call completes.
    """
    global _gemini_waiting_count

    if _gemini_semaphore.locked():
        _gemini_waiting_count += 1
        try:
            yield f"The AI is busy — you're #{_gemini_waiting_count} in line..."
            await _gemini_semaphore.acquire()
        finally:
            _gemini_waiting_count -= 1
    else:
        await _gemini_semaphore.acquire()

    while True:
        async with _gemini_rate_lock:
            now = time.monotonic()
            while _gemini_call_times and now - _gemini_call_times[0] > 60:
                _gemini_call_times.popleft()
            if len(_gemini_call_times) < _GEMINI_MAX_PER_MINUTE:
                _gemini_call_times.append(now)
                return
            wait_time = max(0.0, 60 - (now - _gemini_call_times[0]))
        yield f"Rate limit reached — waiting {wait_time:.0f}s before the next request..."
        await asyncio.sleep(wait_time + 0.05)


def _release_gemini_slot() -> None:
    _gemini_semaphore.release()


# Configuration constants - Business rules for file processing
# ────────────────────────────────────────────────────────────
SUPPORTED_TYPES = {".pdf", ".txt", ".md"}  # File extensions we accept
MAX_FILE_SIZE_MB = 20                       # Maximum upload size limit

INDEX_HTML_PATH = Path(__file__).resolve().parent.parent / "index.html"

# ═════════════════════════════════════════════════════════════════════════════
# ENDPOINT 0: / (Serves the frontend)
# ═════════════════════════════════════════════════════════════════════════════
# Serves the single-file frontend from the same origin as the API, so
# there's no separate frontend host, no CORS complexity for the common case,
# and the OAuth popup/session-cookie flow gets a simple same-origin story.
# No StaticFiles mount is needed -- index.html has no other local assets
# (just the Tailwind CDN <script> tag).

@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse:
    return FileResponse(INDEX_HTML_PATH)


# ═════════════════════════════════════════════════════════════════════════════
# ENDPOINT 1: /health (Health Check)
# ═════════════════════════════════════════════════════════════════════════════
# PURPOSE: Simple liveness probe to verify server is running
# CALLED BY: Frontend on startup; monitoring tools in production
# RETURNS: {"status": "ok"}
# HTTP METHOD: GET
# PROCESS: No processing - immediate response

@app.get("/health")
async def health() -> dict[str, str]:
    """
    Health check endpoint - verify server is alive and responsive.
    
    USE: Frontend calls this first to check if backend is running
    RESPONSE: {"status": "ok"}
    NO PROCESSING: Just returns immediate response
    """
    return {"status": "ok"}


# ═════════════════════════════════════════════════════════════════════════════
# ENDPOINT 2: /process (Main Processing Pipeline, streamed via SSE)
# ═════════════════════════════════════════════════════════════════════════════
# PURPOSE: Coordinate the entire extraction pipeline, streaming real progress
# CALLED BY: Frontend when user uploads a syllabus file
# ACCEPTS: File upload (PDF, TXT, or MD)
# RETURNS: text/event-stream — a "phase" event per pipeline step, then either
#          a final "result" event or an "error" event
# HTTP METHOD: POST
#
# PROCESSING STEPS (In order, each emits a "phase" event before/after):
#  Step 0: Receive & validate uploaded file (still a plain HTTP 400 on failure,
#          since this happens before the stream opens)
#  Step 1: Extract text from file (PDF/TXT/MD)
#  Step 2: Send text to Google Gemini AI
#  Step 3: Validate Gemini's JSON response
#  Step 4: Emit final "result" event with clean events to frontend
#
# ERROR HANDLING:
#  - HTTP 400: file validation failed (type, size, empty) — before streaming starts
#  - All other failures (missing API key, Gemini quota/rate limit, timeout,
#    empty/unparseable AI response, unexpected exceptions) are sent as an
#    in-band "error" SSE event, since the HTTP status is already committed to
#    200 by the time streaming begins.

@app.post("/process")
async def process_syllabus(file: UploadFile = File(...)) -> StreamingResponse:
    """
    Main processing endpoint - orchestrates the entire extraction pipeline.

    INPUT: File upload (PDF, TXT, or MD)
    OUTPUT: A text/event-stream (Server-Sent Events) response. The frontend
            reads this incrementally so it can show real, live status instead
            of a simulated progress bar. Events emitted, in order:

              event: phase  data: {"phase": "extract"|"ai"|"validate"|"queued", "status": "start"|"done", "message": "..."}
              event: error  data: {"phase": "...", "detail": "..."}   (stream ends here)
              event: result data: {"events": [...], "count": N}       (final message)

    File validation (type/size/empty) happens BEFORE the stream opens, so
    those failures can still be plain HTTP 400s. Once streaming starts the
    HTTP status is locked at 200, so every failure after that point must be
    signaled in-band as an "error" event rather than an HTTP error code.
    """

    filename = file.filename or "upload"
    suffix = _file_suffix(filename)
    data = await file.read()
    _validate_upload(filename, suffix, data)

    async def event_stream():
        def sse(event: str, payload: dict[str, Any]) -> str:
            return f"event: {event}\ndata: {json.dumps(payload)}\n\n"

        try:
            # ── Phase 1: extract text from the uploaded file ──────────────
            yield sse("phase", {"phase": "extract", "status": "start", "message": "Extracting text from your file..."})
            try:
                raw_text = await asyncio.to_thread(extract_text_from_bytes, data, filename)
            except ValueError as exc:
                yield sse("error", {"phase": "extract", "detail": str(exc)})
                return
            except ImportError as exc:
                yield sse("error", {"phase": "extract", "detail": str(exc)})
                return

            if not raw_text.strip():
                yield sse("error", {
                    "phase": "extract",
                    "detail": (
                        "No readable text could be extracted. "
                        "If this is a scanned PDF (image-only), the tool cannot process it yet."
                    ),
                })
                return
            yield sse("phase", {"phase": "extract", "status": "done", "message": f"Extracted {len(raw_text)} characters"})

            # ── Phase 2: send extracted text to Google Gemini AI ──────────
            yield sse("phase", {"phase": "ai", "status": "start", "message": "Sending to Gemini AI for analysis..."})
            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            if not api_key:
                yield sse("error", {"phase": "ai", "detail": "Server is missing a Gemini API key. Set GOOGLE_API_KEY on the server."})
                return

            # Wait for a Gemini call slot, honoring the concurrency cap and
            # the shared key's per-minute rate limit. Surfaces an honest
            # "queued" status instead of silence when other requests are
            # ahead of this one.
            async for wait_message in _throttle_gemini():
                yield sse("phase", {"phase": "queued", "status": "start", "message": wait_message})

            model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
            controller = GeminiPipelineController(api_key=api_key, model=model)
            try:
                try:
                    raw_response = await asyncio.wait_for(
                        asyncio.to_thread(controller.generate, raw_text),
                        timeout=45.0,
                    )
                except asyncio.TimeoutError:
                    yield sse("error", {"phase": "ai", "detail": "AI processing took too long (>45 seconds). The API might be overloaded. Try again in a moment."})
                    return
                except Exception as exc:
                    yield sse("error", {"phase": "ai", "detail": _describe_gemini_error(exc)})
                    return
            finally:
                _release_gemini_slot()

            if not raw_response.strip():
                yield sse("error", {"phase": "ai", "detail": "Gemini returned an empty response. Try a cleaner syllabus document."})
                return
            yield sse("phase", {"phase": "ai", "status": "done", "message": "AI analysis complete"})

            # ── Phase 3: validate and normalize the AI response ────────────
            yield sse("phase", {"phase": "validate", "status": "start", "message": "Validating extracted data..."})
            try:
                events: list[dict[str, Any]] = sanitize_model_output(raw_response)
            except ValueError as exc:
                yield sse("error", {
                    "phase": "validate",
                    "detail": f"Could not parse the AI response into calendar events: {exc}. Try uploading a cleaner syllabus document.",
                })
                return
            incomplete_count = sum(1 for e in events if e.get("incomplete"))
            done_message = f"{len(events)} event(s) found"
            if incomplete_count:
                done_message += f" ({incomplete_count} need review)"
            yield sse("phase", {"phase": "validate", "status": "done", "message": done_message})

            # ── Final result ────────────────────────────────────────────────
            yield sse("result", {"events": events, "count": len(events)})
        except Exception as exc:
            yield sse("error", {"phase": "unknown", "detail": f"Unexpected server error: {type(exc).__name__}: {exc}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


# ---------------------------------------------------------------------------
# /download -- convert events JSON back into a .ics file (Phase 5 stub)
# ---------------------------------------------------------------------------

@app.post("/download")
async def download_ics(request: Request) -> PlainTextResponse:
    """Accept a JSON body of events and return a downloadable .ics file.

    Request body: {"events": [ {...}, ... ]}
    Response:     text/calendar with Content-Disposition: attachment
    """
    body = await request.json()
    events: list[dict[str, Any]] = body.get("events", [])

    if not events:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No events provided.",
        )

    try:
        ics_text = build_ics(events)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to build calendar file: {exc}",
        )

    return PlainTextResponse(
        content=ics_text,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="syllabus_events.ics"'},
    )


# ---------------------------------------------------------------------------
# Google Calendar OAuth + push
# ---------------------------------------------------------------------------
# Lets the user push extracted events directly into a dedicated "Syllabus
# Deadlines" Google Calendar instead of manually importing an .ics file.
# Requires a one-time manual setup step in Google Cloud Console — see
# src/calendar_push/google_calendar_client.py for details. Until that's done,
# these routes return a 501 pointing at what's missing.

@app.get("/auth/google/login")
async def google_login(request: Request) -> RedirectResponse:
    """Redirect the browser into Google's OAuth consent screen."""
    session_id = _get_session_id(request)
    try:
        auth_url = gcal.build_authorization_url(session_id)
    except gcal.GoogleCalendarNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc))
    return RedirectResponse(auth_url)


@app.get("/auth/google/callback")
async def google_callback(request: Request) -> HTMLResponse:
    """OAuth redirect target — exchanges the auth code for tokens.

    Renders a tiny page that posts a message back to the window that opened
    it (the main app, waiting in a popup-listener) and then closes itself.
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        detail = f"Google sign-in was cancelled or failed: {error}"
        return _auth_result_page(success=False, detail=detail, provider="google")

    if not code or not state:
        return _auth_result_page(success=False, detail="Missing code/state in Google's redirect.", provider="google")

    try:
        gcal.exchange_code_for_token(code=code, state=state)
    except Exception as exc:
        return _auth_result_page(success=False, detail=str(exc), provider="google")

    return _auth_result_page(success=True, detail="", provider="google")


@app.get("/auth/google/status")
async def google_status(request: Request) -> dict[str, bool]:
    # Also where a first-time visitor's session cookie gets established --
    # the frontend always calls this before opening the sign-in popup.
    session_id = _get_session_id(request)
    return {"connected": gcal.is_connected(session_id)}


@app.post("/auth/google/logout")
async def google_logout(request: Request) -> dict[str, bool]:
    session_id = _get_session_id(request)
    gcal.disconnect(session_id)
    return {"connected": False}


@app.post("/calendar/google/push")
async def calendar_google_push(request: Request) -> JSONResponse:
    """Push a JSON body of events into the visitor's dedicated Google Calendar.

    Request body: {"events": [ {...}, ... ]}
    Response: {"created": N, "failed": [...], "calendar_html_link": "..."}
    """
    session_id = _get_session_id(request)
    body = await request.json()
    events: list[dict[str, Any]] = body.get("events", [])
    if not events:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No events provided.")

    if not gcal.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google Calendar isn't connected yet. Sign in first.",
        )

    try:
        result = await asyncio.to_thread(gcal.push_events, events, session_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to push events to Google Calendar: {exc}",
        )

    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# Microsoft (Outlook/Microsoft 365) Calendar OAuth + push
# ---------------------------------------------------------------------------
# Same shape as the Google routes above. Covers both personal Outlook.com
# accounts and work/school Microsoft 365 accounts (Teams' calendar tab is
# this same backend, not a separate calendar system). Requires a one-time
# manual Azure app registration -- see src/calendar_push/microsoft_calendar_client.py
# and README for details. Until that's done, these routes return a 501.

@app.get("/auth/microsoft/login")
async def microsoft_login(request: Request) -> RedirectResponse:
    """Redirect the browser into Microsoft's OAuth consent screen."""
    session_id = _get_session_id(request)
    try:
        auth_url = mscal.build_authorization_url(session_id)
    except mscal.MicrosoftCalendarNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc))
    return RedirectResponse(auth_url)


@app.get("/auth/microsoft/callback")
async def microsoft_callback(request: Request) -> HTMLResponse:
    """OAuth redirect target — exchanges the auth code for tokens."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        detail = f"Microsoft sign-in was cancelled or failed: {error}"
        return _auth_result_page(success=False, detail=detail, provider="microsoft")

    if not code or not state:
        return _auth_result_page(success=False, detail="Missing code/state in Microsoft's redirect.", provider="microsoft")

    try:
        mscal.exchange_code_for_token(code=code, state=state)
    except Exception as exc:
        return _auth_result_page(success=False, detail=str(exc), provider="microsoft")

    return _auth_result_page(success=True, detail="", provider="microsoft")


@app.get("/auth/microsoft/status")
async def microsoft_status(request: Request) -> dict[str, bool]:
    session_id = _get_session_id(request)
    return {"connected": mscal.is_connected(session_id)}


@app.post("/auth/microsoft/logout")
async def microsoft_logout(request: Request) -> dict[str, bool]:
    session_id = _get_session_id(request)
    mscal.disconnect(session_id)
    return {"connected": False}


@app.post("/calendar/microsoft/push")
async def calendar_microsoft_push(request: Request) -> JSONResponse:
    """Push a JSON body of events into the visitor's dedicated Microsoft Calendar.

    Request body: {"events": [ {...}, ... ]}
    Response: {"created": N, "failed": [...], "calendar_html_link": "..."}
    """
    session_id = _get_session_id(request)
    body = await request.json()
    events: list[dict[str, Any]] = body.get("events", [])
    if not events:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No events provided.")

    if not mscal.is_connected(session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Microsoft Calendar isn't connected yet. Sign in first.",
        )

    try:
        result = await asyncio.to_thread(mscal.push_events, events, session_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to push events to Microsoft Calendar: {exc}",
        )

    return JSONResponse(content=result)


def _auth_result_page(success: bool, detail: str, provider: str = "google") -> HTMLResponse:
    message_type = f"{provider}-auth-success" if success else f"{provider}-auth-error"
    heading = "Connected!" if success else "Sign-in failed"
    body_text = "You can close this window." if success else detail
    payload = json.dumps({"type": message_type, "detail": detail})
    html = f"""<!DOCTYPE html>
<html><head><title>{heading}</title></head>
<body style="font-family: sans-serif; text-align: center; padding: 60px 20px;">
  <h2>{heading}</h2>
  <p>{body_text}</p>
  <script>
    // The opener (main app window) is served by this same FastAPI app, so
    // it shares this page's origin -- target it directly instead of '*'.
    // The listener on the receiving end double-checks
    // evt.origin === window.location.origin before trusting the message.
    if (window.opener) {{
      window.opener.postMessage({payload}, window.location.origin);
    }}
    setTimeout(function() {{ window.close(); }}, 1500);
  </script>
</body></html>"""
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# Global error handler for unexpected exceptions
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": f"Unexpected server error: {type(exc).__name__}: {exc}"},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_suffix(filename: str) -> str:
    return Path(filename).suffix.lower()


def _validate_upload(filename: str, suffix: str, data: bytes) -> None:
    """Validate an uploaded file's type, size, and non-emptiness.

    Raises HTTPException(400) on any failure. Must run before a streaming
    response opens, since HTTP status codes can't change once streaming starts.
    """
    if suffix not in SUPPORTED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{suffix}'. Upload a PDF, TXT, or MD file.",
        )

    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty.",
        )

    size_mb = len(data) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large ({size_mb:.1f} MB). Maximum allowed is {MAX_FILE_SIZE_MB} MB.",
        )


def _describe_gemini_error(exc: Exception) -> str:
    """Translate a Gemini SDK exception into a user-facing message string.

    Used inside the /process SSE stream, where the HTTP status is already
    committed to 200 by the time errors can occur, so they travel as an
    in-band "error" event instead of an HTTPException.
    """
    msg = str(exc).lower()
    if "429" in msg or "quota" in msg or "rate" in msg:
        return (
            "The AI service is busy or its quota is exhausted (429). "
            "Please wait a moment and try again, or check the API key's quota in Google Cloud Console."
        )
    return f"Gemini API error: {exc}"
