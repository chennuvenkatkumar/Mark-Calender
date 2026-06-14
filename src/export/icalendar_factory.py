"""Generate iCalendar payloads for syllabus events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import uuid4


@dataclass(slots=True)
class ExportResult:
    ics_text: str
    output_path: Path | None = None


def build_ics(events: Iterable[dict[str, str]], product_id: str = "-//SyllabusToCalendarAI//AcademicSync v1.0//EN") -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{product_id}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for event in events:
        date_value = event["due_date"]
        time_value = event.get("due_time", "23:59")
        start_dt = datetime.strptime(f"{date_value} {time_value}", "%Y-%m-%d %H:%M")
        start_stamp = start_dt.strftime("%Y%m%dT%H%M%S")

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uuid4()}",
                f"DTSTAMP:{now_stamp}",
                f"SUMMARY:{_escape_ics_text(_summary(event))}",
                f"DTSTART:{start_stamp}",
                f"DESCRIPTION:{_escape_ics_text(_description(event))}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def write_ics_file(events: Iterable[dict[str, str]], output_path: str | Path | None = None) -> ExportResult:
    ics_text = build_ics(events)
    target = _resolve_output_path(output_path)
    target.write_text(ics_text, encoding="utf-8")
    return ExportResult(ics_text=ics_text, output_path=target)


def _summary(event: dict[str, str]) -> str:
    course_name = event.get("course_name", "").strip()
    task_name = event.get("task_name", "").strip()
    if course_name and task_name:
        return f"{course_name} - {task_name}"
    return course_name or task_name


def _description(event: dict[str, str]) -> str:
    description = event.get("description", "").strip()
    if description:
        return description
    return f"Due {event.get('due_date', '')} at {event.get('due_time', '23:59')}"


def _escape_ics_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _resolve_output_path(output_path: str | Path | None) -> Path:
    if output_path is not None:
        return Path(output_path)

    desktop = Path.home() / "Desktop"
    base_dir = desktop if desktop.exists() else Path.cwd()
    return base_dir / "syllabus_events.ics"