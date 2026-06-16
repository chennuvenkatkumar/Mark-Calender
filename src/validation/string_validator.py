"""Validation and normalization for Gemini output."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any


# Fallback time applied to any event whose due_time is absent or empty
DEFAULT_DUE_TIME = "23:59"


def sanitize_model_output(raw_text: str) -> list[dict[str, Any]]:
    """Extract, parse, and validate a JSON array from the raw Gemini response.

    Isolates the JSON block embedded in the raw text, deserialises it, and
    normalises each event dict so downstream code always receives clean,
    consistently-formatted data.

    Returns a list of normalised event dicts.
    Raises ValueError for empty output, non-array JSON, or malformed events.

    Usage:
        events = sanitize_model_output(gemini_raw_response)
    """

    # Isolate the JSON portion from any surrounding prose the model may have added
    payload = _extract_json_block(raw_text)
    parsed = json.loads(payload)

    # The prompt demands an array; reject objects or primitives outright
    if not isinstance(parsed, list):
        raise ValueError("Gemini output must be a JSON array.")

    events: list[dict[str, Any]] = []
    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Event #{index} is not a JSON object.")
        events.append(_normalize_event(item, index))
    return events


def _extract_json_block(raw_text: str) -> str:
    """Scan raw_text and return the first complete, balanced JSON value found.

    Handles both array (`[...]`) and object (`{...}`) root values.  Uses a
    depth counter and a simple string-literal tracker to correctly skip
    brackets inside quoted strings, including escaped quote characters.

    Raises ValueError when the text is empty, contains no JSON, or the
    found JSON structure is never closed.
    """

    text = raw_text.strip()
    if not text:
        raise ValueError("Gemini output was empty.")

    # Find the first '[' or '{', whichever appears earlier in the text
    start = min((idx for idx in (text.find("["), text.find("{")) if idx != -1), default=-1)
    if start == -1:
        raise ValueError("Gemini output does not contain JSON.")

    opener = text[start]
    closer = "]" if opener == "[" else "}"

    # Track nesting depth and whether we are currently inside a JSON string
    depth = 0
    in_string = False
    escape = False

    for position in range(start, len(text)):
        char = text[position]

        if in_string:
            if escape:
                # The previous character was a backslash; this character is literal
                escape = False
            elif char == "\\":
                # Signal that the next character is escaped
                escape = True
            elif char == '"':
                # Closing quote ends the current string literal
                in_string = False
            continue  # Skip bracket counting while inside a string

        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1          # Entering a nested array/object
        elif char == closer:
            depth -= 1
            if depth == 0:
                # Depth returns to zero — we have a complete, balanced structure
                return text[start : position + 1]

    raise ValueError("Unable to isolate a complete JSON payload.")


def _normalize_event(item: dict[str, Any], index: int) -> dict[str, str]:
    """Normalise a single raw event dict from the Gemini response.

    Coerces all field values to strings, strips whitespace, and delegates
    date/time normalisation to the dedicated helpers.  Validates that the
    mandatory fields `course_name` and `task_name` are non-empty.

    Returns a dict with keys: course_name, task_name, due_date, due_time,
    description — all as plain strings.
    """

    course_name = str(item.get("course_name", "")).strip()
    task_name = str(item.get("task_name", "")).strip()
    due_date = _normalize_date(str(item.get("due_date", "")).strip())
    due_time = _normalize_time(str(item.get("due_time", "")).strip())
    description = str(item.get("description", "")).strip()

    # Both identity fields are required; reject events missing either one
    if not course_name:
        raise ValueError(f"Event #{index} is missing course_name.")
    if not task_name:
        raise ValueError(f"Event #{index} is missing task_name.")

    return {
        "course_name": course_name,
        "task_name": task_name,
        "due_date": due_date,
        "due_time": due_time,
        "description": description,
    }


def _normalize_date(value: str) -> str:
    """Convert a date string in any supported format to YYYY-MM-DD.

    Tries each candidate strptime format in order and returns the first match
    reformatted as ISO-8601.  Raises ValueError when the value is empty or
    matches none of the supported formats.

    Supported input formats:
        - YYYY-MM-DD  (ISO-8601, preferred)
        - MM/DD/YYYY  (US long-form)
        - MM/DD/YY    (US short-form)
        - YYYY/MM/DD  (ISO variant with slashes)
    """

    if not value:
        raise ValueError("Each event must include a due_date.")

    candidates = (
        "%Y-%m-%d",   # ISO-8601 — the format Gemini is instructed to return
        "%m/%d/%Y",   # US long-form, e.g. "01/31/2026"
        "%m/%d/%y",   # US short-form, e.g. "01/31/26"
        "%Y/%m/%d",   # ISO with slashes, e.g. "2026/01/31"
    )
    for fmt in candidates:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Unsupported due_date format: {value}")


def _normalize_time(value: str) -> str:
    """Convert a time string in any supported format to HH:MM (24-hour).

    Returns DEFAULT_DUE_TIME ("23:59") when value is empty, matching the
    prompt rule that instructs Gemini to use 23:59 for unspecified times.
    Raises ValueError when the value is present but matches no known format.

    Supported input formats:
        - HH:MM       (24-hour, e.g. "14:30")
        - HH:MM:SS    (24-hour with seconds)
        - HH:MM AM/PM (12-hour with space, e.g. "02:30 PM")
        - HH:MMAM/PM  (12-hour no space, e.g. "02:30PM")
    """

    # Treat an absent time as end-of-day rather than raising an error
    if not value:
        return DEFAULT_DUE_TIME

    candidates = (
        "%H:%M",      # 24-hour short, e.g. "14:30"
        "%H:%M:%S",   # 24-hour with seconds, e.g. "14:30:00"
        "%I:%M %p",   # 12-hour with space before AM/PM, e.g. "02:30 PM"
        "%I:%M%p",    # 12-hour without space, e.g. "02:30PM"
    )
    for fmt in candidates:
        try:
            return datetime.strptime(value, fmt).strftime("%H:%M")
        except ValueError:
            continue
    raise ValueError(f"Unsupported due_time format: {value}")


def extract_event_datetime(event: dict[str, Any]) -> tuple[str, str]:
    """Return the normalised (date, time) pair for a single event dict.

    Convenience wrapper used by callers that need to extract and validate
    the date/time fields from an already-parsed event without running the
    full sanitize_model_output pipeline.

    Returns:
        (due_date, due_time) — both strings in YYYY-MM-DD and HH:MM format.

    Usage:
        date_str, time_str = extract_event_datetime(event)
    """

    return _normalize_date(str(event["due_date"])), _normalize_time(str(event.get("due_time", "")))
