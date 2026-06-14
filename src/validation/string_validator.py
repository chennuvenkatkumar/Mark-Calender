"""Validation and normalization for Gemini output."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any


DEFAULT_DUE_TIME = "23:59"
def sanitize_model_output(raw_text: str) -> list[dict[str, Any]]:
    """Extract and validate JSON from a model response."""

    payload = _extract_json_block(raw_text)
    parsed = json.loads(payload)
    if not isinstance(parsed, list):
        raise ValueError("Gemini output must be a JSON array.")

    events: list[dict[str, Any]] = []
    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Event #{index} is not a JSON object.")
        events.append(_normalize_event(item, index))
    return events


def _extract_json_block(raw_text: str) -> str:
    text = raw_text.strip()
    if not text:
        raise ValueError("Gemini output was empty.")

    start = min((idx for idx in (text.find("["), text.find("{")) if idx != -1), default=-1)
    if start == -1:
        raise ValueError("Gemini output does not contain JSON.")

    opener = text[start]
    closer = "]" if opener == "[" else "}"
    depth = 0
    in_string = False
    escape = False

    for position in range(start, len(text)):
        char = text[position]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : position + 1]

    raise ValueError("Unable to isolate a complete JSON payload.")


def _normalize_event(item: dict[str, Any], index: int) -> dict[str, str]:
    course_name = str(item.get("course_name", "")).strip()
    task_name = str(item.get("task_name", "")).strip()
    due_date = _normalize_date(str(item.get("due_date", "")).strip())
    due_time = _normalize_time(str(item.get("due_time", "")).strip())
    description = str(item.get("description", "")).strip()

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
    if not value:
        raise ValueError("Each event must include a due_date.")

    candidates = (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y/%m/%d",
    )
    for fmt in candidates:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Unsupported due_date format: {value}")


def _normalize_time(value: str) -> str:
    if not value:
        return DEFAULT_DUE_TIME

    candidates = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p")
    for fmt in candidates:
        try:
            return datetime.strptime(value, fmt).strftime("%H:%M")
        except ValueError:
            continue
    raise ValueError(f"Unsupported due_time format: {value}")


def extract_event_datetime(event: dict[str, Any]) -> tuple[str, str]:
    """Return the normalized date/time pair for an event."""

    return _normalize_date(str(event["due_date"])), _normalize_time(str(event.get("due_time", "")))
