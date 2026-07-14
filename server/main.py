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
GET  /health    → {"status": "ok"}              [Health check]
POST /process   → {"events": [...], "count": N} [Main processing]
POST /download  → binary .ics file              [Calendar export]

Run locally:
    uvicorn server.main:app --reload --port 8000

Environment variables required:
    GOOGLE_API_KEY (from Google Cloud Console)
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status

# Load environment variables from .env file at startup
# This makes GOOGLE_API_KEY available via os.getenv()
load_dotenv()

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

import asyncio
import json
import time

# Import the four layers of the processing pipeline
from src.ingest.file_ingestor import extract_text_from_bytes
from src.ai.gemini_pipeline_controller import GeminiPipelineController
from src.validation.string_validator import sanitize_model_output
from src.export.icalendar_factory import build_ics

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
# PROBLEM: Frontend runs at file:///C:/Users/.../index.html (file protocol)
#          Backend runs at http://localhost:8000 (http protocol)
#          Browsers block requests between different origins by default
#
# SOLUTION: Enable CORS to allow frontend to call backend API
# 
# allow_origins=["*"]: Accept requests from ANY origin (not secure for production)
# allow_methods=["GET", "POST"]: Only allow these HTTP methods
# allow_headers=["*"]: Accept any request headers
#
# Production note: In real deployment, restrict origins to your domain only
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Configuration constants - Business rules for file processing
# ────────────────────────────────────────────────────────────
SUPPORTED_TYPES = {".pdf", ".txt", ".md"}  # File extensions we accept
MAX_FILE_SIZE_MB = 20                       # Maximum upload size limit

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
# ENDPOINT 2: /process (Main Processing Pipeline)
# ═════════════════════════════════════════════════════════════════════════════
# PURPOSE: Coordinate the entire extraction and processing pipeline
# CALLED BY: Frontend when user uploads a syllabus file
# ACCEPTS: File upload (PDF, TXT, or MD)
# RETURNS: {"events": [{...}, {...}], "count": N}
# HTTP METHOD: POST
#
# PROCESSING STEPS (In order):
#  Step 1: Receive & validate uploaded file
#  Step 2: Extract text from file (PDF/TXT/MD)
#  Step 3: Send text to Google Gemini AI
#  Step 4: Validate Gemini's JSON response
#  Step 5: Return clean events to frontend
#
# ERROR HANDLING:
#  - 400: File validation failed (type, size, empty, etc.)
#  - 429: Rate limit hit (Gemini free tier: 15 requests/minute)
#  - 422: Gemini response couldn't be parsed as JSON
#  - 500: Unexpected server error
#  - 504: Gemini took too long (>45 seconds)

@app.post("/process")
async def process_syllabus(file: UploadFile = File(...)) -> JSONResponse:
    """
    Main processing endpoint - orchestrates the entire extraction pipeline.
    
    INPUT: File upload (PDF, TXT, or MD)
    OUTPUT: {"events": [{...}, {...}], "count": N}
    
    WORKFLOW:
    ┌─ STEP 1: Receive & Validate File ──────────────────────────┐
    │  • Get filename and file extension                          │
    │  • Check file type is in SUPPORTED_TYPES                    │
    │  • Check file is not empty                                  │
    │  • Check file size doesn't exceed MAX_FILE_SIZE_MB          │
    │  • If any validation fails → raise HTTPException with 400   │
    └────────────────────────────────────────────────────────────┘
    
    ┌─ STEP 2: Extract Text from File ──────────────────────────┐
    │  • Calls: extract_text_from_bytes(data, filename)          │
    │  • Routes to correct extractor based on file type          │
    │  • PDF → Uses PyMuPDF to read each page                    │
    │  • TXT/MD → Decodes as UTF-8 text                         │
    │  • Returns: Raw text string from the file                  │
    │  • If fails → raise HTTPException with 400/500            │
    └────────────────────────────────────────────────────────────┘
    
    ┌─ STEP 3: Send to Google Gemini AI ─────────────────────────┐
    │  • Get GOOGLE_API_KEY from .env file                       │
    │  • Create GeminiPipelineController instance                │
    │  • Build prompt by injecting extracted text                │
    │  • Send to Gemini API with asyncio.wait_for() wrapper      │
    │  • TIMEOUT: 45 seconds max (prevents hanging)              │
    │  • Returns: Raw JSON response from Gemini                  │
    │  • If fails → raise HTTPException with 429/504/500         │
    └────────────────────────────────────────────────────────────┘
    
    ┌─ STEP 4: Validate & Normalize Response ────────────────────┐
    │  • Calls: sanitize_model_output(raw_response)              │
    │  • Extracts JSON block from response                       │
    │  • Validates JSON structure (must be array)                │
    │  • For each event:                                         │
    │    - Normalizes dates to YYYY-MM-DD format                │
    │    - Normalizes times to HH:MM format (24-hour)           │
    │    - Validates required fields                             │
    │  • Returns: List of clean, normalized event dicts          │
    │  • If fails → raise HTTPException with 422                │
    └────────────────────────────────────────────────────────────┘
    
    ┌─ STEP 5: Return to Frontend ───────────────────────────────┐
    │  • Returns JSONResponse with:                              │
    │    - "events": List of extracted & normalized events       │
    │    - "count": Number of events extracted                   │
    │  • Frontend receives this JSON and displays events         │
    └────────────────────────────────────────────────────────────┘
    """

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1: Read and validate the uploaded file
    # ─────────────────────────────────────────────────────────────────────────
    filename = file.filename or "upload"
    suffix = _file_suffix(filename)

    # Validate file type
    if suffix not in SUPPORTED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{suffix}'. Upload a PDF, TXT, or MD file.",
        )

    # Read file into memory (never written to disk for security)
    data = await file.read()

    # Validate file is not empty
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty.",
        )

    # Validate file size doesn't exceed limit
    size_mb = len(data) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large ({size_mb:.1f} MB). Maximum allowed is {MAX_FILE_SIZE_MB} MB.",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 2: Extract text from uploaded file
    # ─────────────────────────────────────────────────────────────────────────
    # This calls src/ingest/file_ingestor.py
    # For PDF: Uses PyMuPDF to read each page and extract text
    # For TXT/MD: Decodes as UTF-8 string
    try:
        raw_text = extract_text_from_bytes(data, filename)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    # Validate we actually extracted text
    if not raw_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No readable text could be extracted. "
                "If this is a scanned PDF (image-only), the tool cannot process it yet."
            ),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3: Send extracted text to Google Gemini AI
    # ─────────────────────────────────────────────────────────────────────────
    # Algorithm: Async wrapper with timeout to prevent hanging
    # 
    # Why async? Server can handle multiple requests concurrently
    # Why timeout? Gemini might be slow or overloaded
    # Max 45 seconds prevents resources from being held too long
    
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server is missing a Gemini API key. Set GOOGLE_API_KEY on the server.",
        )

    controller = GeminiPipelineController(api_key=api_key)
    try:
        # asyncio.wait_for(): Enforce 45-second timeout on API call
        # asyncio.to_thread(): Run blocking Gemini API in thread pool
        # This keeps the main event loop responsive to other requests
        raw_response = await asyncio.wait_for(
            asyncio.to_thread(controller.generate, raw_text),
            timeout=45.0
        )
        
        # Verify Gemini actually returned something
        if not raw_response.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Gemini returned an empty response. Try a cleaner syllabus document.",
            )
    except asyncio.TimeoutError:
        # Timeout exception when Gemini takes too long
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="AI processing took too long (>45 seconds). The API might be overloaded. Try again in a moment.",
        )
    except Exception as exc:
        # All other exceptions get mapped to appropriate HTTP errors
        _handle_gemini_error(exc)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 4: Validate and normalize the AI response
    # ─────────────────────────────────────────────────────────────────────────
    # This calls src/validation/string_validator.py
    # Algorithm:
    #  1. Extract JSON block from Gemini response (might have extra text)
    #  2. Parse as JSON array
    #  3. For each event, validate required fields
    #  4. Normalize dates: any format → YYYY-MM-DD
    #  5. Normalize times: any format → HH:MM (24-hour)
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

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 5: Return successful response to frontend
    # ─────────────────────────────────────────────────────────────────────────
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
