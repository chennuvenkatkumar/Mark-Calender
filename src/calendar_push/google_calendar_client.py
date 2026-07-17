"""Google Calendar OAuth 2.0 connection and event push.

Handles the whole Google Calendar side of the app: the OAuth 2.0
"Web application" consent flow, per-visitor credential storage/refresh, and
pushing extracted syllabus events into a dedicated "Syllabus Deadlines"
calendar so a user's personal calendar stays uncluttered.

Credentials are kept in memory only, keyed by an opaque per-visitor session
id (see server/main.py's SessionMiddleware) -- never written to disk. This
matters once the app is hosted for multiple concurrent users: a single
shared credential file would let one visitor's request read or clobber
another's Google account. It also matches the app's "authenticate, mark the
calendar, forget the user" design -- nothing about a visitor survives past
their session (or a server restart).

Requires a one-time manual setup step (either locally or on whichever host
runs this): enable the Calendar API in Google Cloud Console, create a "Web
application" OAuth client with a redirect URI matching OAUTH_REDIRECT_URI,
and either save the downloaded client JSON to .secrets/client_secret.json
(simplest for local dev) or set GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET
as environment variables (safer for hosts with ephemeral disks, where a
file saved at runtime might not survive a redeploy). See README for the
full walkthrough.
"""

from __future__ import annotations

import json
import os
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

REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
CALENDAR_SUMMARY = "Syllabus Deadlines"
EVENT_DURATION_MINUTES = 30

SECRETS_DIR = Path(__file__).resolve().parents[2] / ".secrets"
CLIENT_SECRET_PATH = SECRETS_DIR / "client_secret.json"

# In-flight OAuth attempts, keyed by the "state" token issued in the
# authorization URL. Stores (Flow, session_id): the same Flow object must be
# reused between build_authorization_url() and exchange_code_for_token(),
# because Flow generates a fresh random PKCE code_verifier per instance --
# reusing a different Flow for the token exchange sends a mismatched
# verifier and Google silently rejects the exchange. session_id records
# which visitor this login attempt belongs to, so the exchanged credentials
# land in the right person's bucket. In-memory only; doesn't survive a
# server restart (fine -- an interrupted sign-in just needs retrying).
_pending_flows: dict[str, tuple[Flow, str]] = {}

# Per-visitor credential storage, keyed by an opaque session id. Each bucket
# holds the same JSON shape as Credentials.to_json(), plus a cached
# "calendar_id" once that visitor's dedicated calendar exists. In-memory
# only -- no database, nothing written to disk per-user.
_sessions: dict[str, dict[str, Any]] = {}


class GoogleCalendarNotConfigured(Exception):
    """Raised when no OAuth client is configured, via file or env vars."""


def is_client_configured() -> bool:
    """Whether the OAuth client is set up, either as a local file or env vars."""
    return CLIENT_SECRET_PATH.exists() or bool(
        os.getenv("GOOGLE_OAUTH_CLIENT_ID") and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    )


def _new_flow() -> Flow:
    """Build a Flow from the local client_secret.json if present, else from
    GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET environment variables.

    The file path is the simplest local-dev setup and needs no change to an
    already-working local workflow. The env-var path exists because most
    hosting platforms' free/low tiers have ephemeral disks that don't
    reliably persist across redeploys, making a file-based secret fragile
    in production.
    """
    if CLIENT_SECRET_PATH.exists():
        return Flow.from_client_secrets_file(
            str(CLIENT_SECRET_PATH),
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI,
        )

    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    if client_id and client_secret:
        client_config = {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=REDIRECT_URI)

    raise GoogleCalendarNotConfigured(
        "Google Calendar isn't set up yet. Save your OAuth client JSON to "
        f"{CLIENT_SECRET_PATH}, or set GOOGLE_OAUTH_CLIENT_ID and "
        "GOOGLE_OAUTH_CLIENT_SECRET (see setup instructions)."
    )


def build_authorization_url(session_id: str) -> str:
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
    _pending_flows[state] = (flow, session_id)
    return auth_url


def exchange_code_for_token(code: str, state: str) -> None:
    """Exchange the callback's auth code for tokens, stored under that visitor's session.

    Reuses the exact Flow instance created in build_authorization_url() so
    its PKCE code_verifier matches the code_challenge Google already
    received -- a fresh Flow here would generate a different verifier and
    Google would reject the exchange.
    """
    pending = _pending_flows.pop(state, None)
    if pending is None:
        raise ValueError("Invalid or expired OAuth state (possible CSRF or stale link).")
    flow, session_id = pending

    flow.fetch_token(code=code)
    creds = flow.credentials

    bucket = _sessions.setdefault(session_id, {})
    bucket.update(json.loads(creds.to_json()))


def is_connected(session_id: str) -> bool:
    bucket = _sessions.get(session_id, {})
    return bool(bucket.get("refresh_token") or bucket.get("token"))


def disconnect(session_id: str) -> None:
    _sessions.pop(session_id, None)


def _get_credentials(session_id: str) -> Credentials:
    bucket = _sessions.get(session_id, {})
    if not bucket.get("token") and not bucket.get("refresh_token"):
        raise RuntimeError("Google Calendar isn't connected yet.")

    creds = Credentials.from_authorized_user_info(bucket, scopes=SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
        bucket.update(json.loads(creds.to_json()))
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


def _get_or_create_calendar_id(service, session_id: str) -> str:
    """Return this visitor's dedicated calendar id, creating it on first use.

    Deliberately never calls calendarList().list() -- that endpoint lists
    the user's ENTIRE calendar list (including calendars this app didn't
    create) and the calendar.app.created scope forbids it outright (403
    "insufficient authentication scopes"). Instead, the id is cached in
    this visitor's session bucket after creation and re-validated with
    calendars().get(), which IS permitted for a calendar this app created.
    """
    bucket = _sessions.setdefault(session_id, {})
    cached_id = bucket.get("calendar_id")
    if cached_id:
        try:
            service.calendars().get(calendarId=cached_id).execute()
            return cached_id
        except Exception:
            pass  # cached calendar no longer exists/reachable — recreate below

    created = service.calendars().insert(
        body={"summary": CALENDAR_SUMMARY, "timeZone": _local_timezone()}
    ).execute()
    bucket["calendar_id"] = created["id"]
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


def push_events(events: list[dict[str, str]], session_id: str) -> dict[str, Any]:
    """Push events into this visitor's dedicated "Syllabus Deadlines" calendar.

    Returns {"created": N, "failed": [{"event": ..., "error": ...}, ...],
    "calendar_id": ..., "calendar_html_link": ...}. Never raises on a
    per-event failure — one bad event shouldn't sink the whole batch.
    """
    creds = _get_credentials(session_id)
    service = build("calendar", "v3", credentials=creds)
    calendar_id = _get_or_create_calendar_id(service, session_id)
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
