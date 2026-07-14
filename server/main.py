"""FastAPI backend for the Syllabus-to-Calendar web application.

Endpoints
---------
GET  /health    -- liveness check, returns {"status": "ok"}
POST /process   -- accepts a syllabus file upload, returns extracted events as JSON
POST /download  -- accepts events JSON, returns a .ics file download (Phase 5)

Run locally:
    uvicorn server.main:app --reload --port 8000

Required environment variable:
    GOOGLE_API_KEY  or  GEMINI_API_KEY
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status

load_dotenv()
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from src.ingest.file_ingestor import extract_text_from_bytes
from src.ai.gemini_pipeline_controller import GeminiPipelineController
from src.validation.string_validator import sanitize_model_output
from src.export.icalendar_factory import build_ics

app = FastAPI(title="Syllabus-to-Calendar API", version="1.0.0")

# Allow the frontend HTML file to call this API from any origin (file://, localhost:*, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

SUPPORTED_TYPES = {".pdf", ".txt", ".md"}
MAX_FILE_SIZE_MB = 20


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# /process -- ingest syllabus file and return extracted events
# ---------------------------------------------------------------------------

@app.post("/process")
async def process_syllabus(file: UploadFile = File(...)) -> JSONResponse:
    """Accept a syllabus upload, run the full extraction pipeline, return events.

    Returns a JSON array of event objects:
        [{"course_name": "...", "task_name": "...", "due_date": "YYYY-MM-DD",
          "due_time": "HH:MM", "description": "..."}, ...]

    Error responses use standard HTTP status codes:
        400  unsupported file type / empty file / unreadable content
        422  Gemini returned output that could not be parsed into events
        429  Google API rate limit hit (free tier: 15 RPM)
        500  unexpected server error
    """

    # --- 1. Read file into memory ----------------------------------------
    filename = file.filename or "upload"
    suffix = _file_suffix(filename)

    if suffix not in SUPPORTED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{suffix}'. Upload a PDF, TXT, or MD file.",
        )

    data = await file.read()

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

    # --- 2. Extract text from bytes (never written to disk) ---------------
    try:
        raw_text = extract_text_from_bytes(data, filename)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    if not raw_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No readable text could be extracted. "
                "If this is a scanned PDF (image-only), the tool cannot process it yet."
            ),
        )

    # --- 3. Send to Gemini -----------------------------------------------
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server is missing a Gemini API key. Set GOOGLE_API_KEY on the server.",
        )

    controller = GeminiPipelineController(api_key=api_key)
    try:
        raw_response = controller.generate(raw_text)
    except Exception as exc:
        _handle_gemini_error(exc)

    # --- 4. Validate and normalise ----------------------------------------
    try:
        events: list[dict[str, Any]] = sanitize_model_output(raw_response)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Could not parse the AI response into calendar events: {exc}. "
                "Try uploading a cleaner syllabus document."
            ),
        )

    return JSONResponse(content={"events": events, "count": len(events)})


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
    from pathlib import Path
    return Path(filename).suffix.lower()


def _handle_gemini_error(exc: Exception) -> None:
    """Translate Gemini SDK exceptions into appropriate HTTP errors."""
    msg = str(exc).lower()
    if "429" in msg or "quota" in msg or "rate" in msg:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "The AI service is busy (rate limit reached). "
                "Please wait a moment and try again."
            ),
        )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Gemini API error: {exc}",
    )
