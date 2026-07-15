"""Google Calendar OAuth 2.0 connection and event push.

Handles the whole Google Calendar side of the app: the OAuth 2.0
"Web application" consent flow, on-disk credential storage/refresh, and
pushing extracted syllabus events into a dedicated "Syllabus Deadlines"
calendar so a user's personal calendar stays uncluttered.

Requires a one-time manual setup step the user performs in Google Cloud
Console (enable the Calendar API, create a "Web application" OAuth client
with redirect URI http://localhost:8000/auth/google/callback, and save the
downloaded client JSON to .secrets/client_secret.json). See README/plan for
the full walkthrough.
"""

from __future__ import annotations

import json
import secrets as secrets_module
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

try:
    from tzlocal import get_localzone_name
except ImportError:  # pragma: no cover - tzlocal is a required dependency
    get_localzone_name = None  # type: ignore[assignment]


# Restricted scope: only lets this app manage calendars/events it created
# itself, rather than requesting full access to the user's whole account.
SCOPES = ["https://www.googleapis.com/auth/calendar.app.created"]

REDIRECT_URI = "http://localhost:8000/auth/google/callback"
CALENDAR_SUMMARY = "Syllabus Deadlines"
EVENT_DURATION_MINUTES = 30

SECRETS_DIR = Path(__file__).resolve().parents[2] / ".secrets"
CLIENT_SECRET_PATH = SECRETS_DIR / "client_secret.json"
STATE_PATH = SECRETS_DIR / "google_state.json"

# In-memory CSRF state tokens issued by build_authorization_url() and
# consumed by exchange_code_for_token(). Fine for a single-process,
# single-user local server; not meant to survive a server restart.
_pending_states: set[str] = set()


class GoogleCalendarNotConfigured(Exception):
    """Raised when .secrets/client_secret.json hasn't been set up yet."""


def is_client_configured() -> bool:
    """Whether the user has completed the Cloud Console setup step."""
    return CLIENT_SECRET_PATH.exists()


def _new_flow(state: str | None = None) -> Flow:
    if not CLIENT_SECRET_PATH.exists():
        raise GoogleCalendarNotConfigured(
            "Google Calendar isn't set up yet. Save your OAuth client JSON "
            f"to {CLIENT_SECRET_PATH} first (see setup instructions)."
        )
    return Flow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH),
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
        state=state,
    )


def build_authorization_url() -> str:
    """Build the Google consent-screen URL for a fresh login attempt."""
    flow = _new_flow()
    # prompt="consent" forces Google to re-issue a refresh_token every time;
    # without it, a refresh_token is only granted on the very first-ever
    # consent, and silently omitted on any subsequent re-auth.
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    _pending_states.add(state)
    return auth_url


def exchange_code_for_token(code: str, state: str) -> None:
    """Exchange the callback's auth code for tokens and persist them."""
    if state not in _pending_states:
        raise ValueError("Invalid or expired OAuth state (possible CSRF or stale link).")
    _pending_states.discard(state)

    flow = _new_flow(state=state)
    flow.fetch_token(code=code)
    creds = flow.credentials

    existing = _load_state()
    existing.update(json.loads(creds.to_json()))
    _save_state(existing)


def is_connected() -> bool:
    state = _load_state()
    return bool(state.get("refresh_token") or state.get("token"))


def disconnect() -> None:
    STATE_PATH.unlink(missing_ok=True)


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _save_state(data: dict[str, Any]) -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _get_credentials() -> Credentials:
    state = _load_state()
    if not state.get("token") and not state.get("refresh_token"):
        raise RuntimeError("Google Calendar isn't connected yet.")

    creds = Credentials.from_authorized_user_info(state, scopes=SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
        updated = _load_state()
        updated.update(json.loads(creds.to_json()))
        _save_state(updated)
    return creds


def _local_timezone() -> str:
    if get_localzone_name is not None:
        try:
            name = get_localzone_name()
            if name:
                return name
        except Exception:
            pass
    return "UTC"


def _get_or_create_calendar_id(service) -> str:
    state = _load_state()
    cached_id = state.get("calendar_id")
    if cached_id:
        try:
            service.calendars().get(calendarId=cached_id).execute()
            return cached_id
        except Exception:
            pass  # cached calendar no longer exists/reachable — recreate below

    calendar_list = service.calendarList().list().execute()
    for entry in calendar_list.get("items", []):
        if entry.get("summary") == CALENDAR_SUMMARY:
            state["calendar_id"] = entry["id"]
            _save_state(state)
            return entry["id"]

    created = service.calendars().insert(
        body={"summary": CALENDAR_SUMMARY, "timeZone": _local_timezone()}
    ).execute()
    state["calendar_id"] = created["id"]
    _save_state(state)
    return created["id"]


def _build_event_body(event: dict[str, str], timezone: str) -> dict[str, Any]:
    due_date = event.get("due_date", "")
    due_time = event.get("due_time", "23:59")
    start_dt = datetime.strptime(f"{due_date} {due_time}", "%Y-%m-%d %H:%M")
    end_dt = start_dt + timedelta(minutes=EVENT_DURATION_MINUTES)

    course_name = (event.get("course_name") or "").strip()
    task_name = (event.get("task_name") or "").strip()
    summary = f"{course_name} - {task_name}" if course_name and task_name else (course_name or task_name)

    return {
        "summary": summary,
        "description": event.get("description", ""),
        "start": {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": timezone},
        "end": {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": timezone},
    }


def push_events(events: list[dict[str, str]]) -> dict[str, Any]:
    """Push events into the dedicated "Syllabus Deadlines" calendar.

    Returns {"created": N, "failed": [{"event": ..., "error": ...}, ...],
    "calendar_id": ..., "calendar_html_link": ...}. Never raises on a
    per-event failure — one bad event shouldn't sink the whole batch.
    """
    creds = _get_credentials()
    service = build("calendar", "v3", credentials=creds)
    calendar_id = _get_or_create_calendar_id(service)
    timezone = _local_timezone()

    created = 0
    failed: list[dict[str, str]] = []
    for event in events:
        try:
            body = _build_event_body(event, timezone)
            service.events().insert(calendarId=calendar_id, body=body).execute()
            created += 1
        except Exception as exc:
            failed.append({"event": event.get("task_name", "Untitled event"), "error": str(exc)})

    return {
        "created": created,
        "failed": failed,
        "calendar_id": calendar_id,
        "calendar_html_link": f"https://calendar.google.com/calendar/r?cid={quote(calendar_id)}",
    }
