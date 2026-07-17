"""Generate iCalendar payloads for syllabus events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import uuid4


@dataclass(slots=True)
class ExportResult:
    """Holds the output of a successful ICS export operation.

    Attributes:
        ics_text:    The full RFC 5545-compliant ICS string that was written.
        output_path: Absolute path of the file that was created, or None if
                     only the in-memory text was requested.
    """

    ics_text: str
    output_path: Path | None = None


def build_ics(
    events: Iterable[dict[str, str]],
    product_id: str = "-//SyllabusToCalendarAI//AcademicSync v1.0//EN",
) -> str:
    """Build a complete RFC 5545 VCALENDAR string from a sequence of event dicts.

    Each event dict must contain at least `due_date` (YYYY-MM-DD) and
    optionally `due_time` (HH:MM, defaults to "23:59").  Additional keys
    (`course_name`, `task_name`, `description`) are forwarded to the VEVENT
    SUMMARY and DESCRIPTION properties.

    The returned string uses CRLF line endings as required by the iCalendar spec.

    Usage:
        ics_text = build_ics(normalised_events)
    """

    # VCALENDAR wrapper required by RFC 5545 — all events are nested inside
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{product_id}",      # Identifies the software that created the file
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",            # PUBLISH means read-only subscription, not an invite
    ]

    # Capture the current UTC moment once and reuse it as DTSTAMP for all events
    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for event in events:
        date_value = event.get("due_date", "")
        time_value = event.get("due_time") or "23:59"

        # Combine date and time into a single datetime for consistent formatting.
        # Skip (rather than abort the whole export) events with a missing or
        # unparseable date -- e.g. one left blank during manual entry -- so
        # the rest of a batch still downloads successfully.
        try:
            start_dt = datetime.strptime(f"{date_value} {time_value}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue

        # iCalendar local-time format (no Z suffix) — avoids timezone conversion issues
        start_stamp = start_dt.strftime("%Y%m%dT%H%M%S")

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uuid4()}",                                      # Globally unique event ID
                f"DTSTAMP:{now_stamp}",                                # When the ICS was generated
                f"SUMMARY:{_escape_ics_text(_summary(event))}",        # Calendar entry title
                f"DTSTART:{start_stamp}",                              # Event start date/time
                f"DESCRIPTION:{_escape_ics_text(_description(event))}", # Detail text shown in calendar
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")

    # RFC 5545 mandates CRLF (\r\n) line endings throughout the ICS file
    return "\r\n".join(lines) + "\r\n"


def write_ics_file(
    events: Iterable[dict[str, str]],
    output_path: str | Path | None = None,
) -> ExportResult:
    """Write an ICS file to disk and return an ExportResult with the path.

    When output_path is None the file is saved as `syllabus_events.ics` on
    the user's Desktop (if it exists) or in the current working directory.

    Usage:
        result = write_ics_file(events, output_path="my_schedule.ics")
        print(result.output_path)   # resolved absolute path
    """

    ics_text = build_ics(events)
    target = _resolve_output_path(output_path)
    target.write_text(ics_text, encoding="utf-8")
    return ExportResult(ics_text=ics_text, output_path=target)


def _summary(event: dict[str, str]) -> str:
    """Build the SUMMARY (title) string for a calendar event.

    Combines course_name and task_name with " - " when both are present.
    Falls back to whichever field is non-empty when only one exists.

    Example output: "CS101 Intro to Programming - Midterm Exam"
    """

    course_name = event.get("course_name", "").strip()
    task_name = event.get("task_name", "").strip()
    if course_name and task_name:
        return f"{course_name} - {task_name}"

    # Return whichever single field is available rather than an empty string
    return course_name or task_name


def _description(event: dict[str, str]) -> str:
    """Build the DESCRIPTION body text for a calendar event.

    Returns the event's `description` field when present; otherwise falls back
    to a human-readable "Due <date> at <time>" sentence so the calendar entry
    always contains some useful context.
    """

    description = event.get("description", "").strip()
    if description:
        return description

    # Fallback keeps the event informative even when no description was extracted
    return f"Due {event.get('due_date', '')} at {event.get('due_time', '23:59')}"


def _escape_ics_text(value: str) -> str:
    """Escape special characters in a string for safe embedding in ICS property values.

    RFC 5545 requires that backslashes, semicolons, and commas inside text
    properties are escaped, and that newlines are encoded as the literal
    two-character sequence "\\n".

    Backslashes must be escaped first to avoid double-escaping the sequences
    introduced in subsequent replace calls.
    """

    return (
        value.replace("\\", "\\\\")   # Must be first — escapes the escape character itself
        .replace(";", r"\;")           # Semicolons delimit multi-value properties
        .replace(",", r"\,")           # Commas delimit list values in some properties
        .replace("\r\n", "\\n")        # Windows-style newline → ICS encoded newline
        .replace("\n", "\\n")          # Unix-style newline → ICS encoded newline
    )


def _resolve_output_path(output_path: str | Path | None) -> Path:
    """Resolve the target file path for the ICS export.

    When output_path is provided, it is returned as-is (converted to Path).
    When None, the function writes to the user's Desktop if it exists, falling
    back to the current working directory if the Desktop cannot be found.

    Returns an absolute Path object pointing to `syllabus_events.ics`.
    """

    if output_path is not None:
        return Path(output_path)

    # Prefer the Desktop so the file is immediately visible to the user
    desktop = Path.home() / "Desktop"
    base_dir = desktop if desktop.exists() else Path.cwd()
    return base_dir / "syllabus_events.ics"