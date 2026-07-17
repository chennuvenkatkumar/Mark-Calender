"""Iteration 1 CLI runner -- processes a syllabus file and writes a .ics calendar file.

Usage:
    py main.py <path-to-syllabus>

Examples:
    py main.py syllabus.pdf
    py main.py "C:/Users/venkat/Downloads/CS101_syllabus.pdf"

The script reads the file, sends it to Gemini, validates the response,
and writes syllabus_events.ics to the Desktop (or current directory).

Required environment variable:
    GOOGLE_API_KEY  or  GEMINI_API_KEY
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.ingest.file_ingestor import extract_text
from src.ai.gemini_pipeline_controller import GeminiPipelineController
from src.validation.string_validator import sanitize_model_output
from src.export.icalendar_factory import write_ics_file


def run(file_path: str) -> None:
    path = Path(file_path)

    print(f"[1/4] Reading file: {path.name}")
    try:
        raw_text = extract_text(path)
    except FileNotFoundError:
        print(f"ERROR: File not found -- {path}")
        sys.exit(1)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    if not raw_text.strip():
        print("ERROR: No readable text found in the file. Is it a scanned image PDF?")
        sys.exit(1)

    print(f"[2/4] Sending to Gemini ({len(raw_text)} characters extracted)...")
    controller = GeminiPipelineController()
    try:
        raw_response = controller.generate(raw_text)
    except ValueError as exc:
        # Missing API key
        print(f"ERROR: {exc}")
        print("Set your key:  $env:GOOGLE_API_KEY='your-key-here'  (PowerShell)")
        sys.exit(1)
    except Exception as exc:
        print(f"ERROR: Gemini API call failed -- {exc}")
        sys.exit(1)

    print("[3/4] Validating and normalising AI response...")
    try:
        events = sanitize_model_output(raw_response)
    except ValueError as exc:
        print(f"ERROR: Could not parse Gemini output -- {exc}")
        print("Raw response preview:")
        print(raw_response[:500])
        sys.exit(1)

    print(f"[4/4] Writing .ics file ({len(events)} event(s) found)...")
    result = write_ics_file(events)

    print()
    print("Done.")
    print(f"Calendar saved to: {result.output_path}")
    print()
    print("Events extracted:")
    for i, event in enumerate(events, 1):
        print(f"  {i:>2}. [{event['due_date']} {event['due_time']}]  "
              f"{event['course_name']} -- {event['task_name']}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage:  py main.py <path-to-syllabus>")
        print("Example: py main.py syllabus.pdf")
        sys.exit(1)

    run(sys.argv[1])
