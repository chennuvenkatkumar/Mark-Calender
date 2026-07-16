"""Microsoft Graph (Outlook/Microsoft 365 Calendar) OAuth 2.0 and event push.

Mirrors google_calendar_client.py's shape and design philosophy: per-visitor
credentials held in memory only, keyed by an opaque session id (see
server/main.py's SessionMiddleware) -- never written to disk, wiped on a
server restart. Same "authenticate, mark the calendar, forget the user"
design as the Google integration.

Two real differences from the Google side, worth reading before touching
this file:

1. No PKCE, no per-request Flow object. Microsoft's low-level MSAL API pair
   (get_authorization_request_url / acquire_token_by_authorization_code)
   does no PKCE at all -- a confidential client authenticates via its
   client secret instead. That means a single, long-lived
   ConfidentialClientApplication built once at import time is correct and
   is Microsoft's own recommended pattern, unlike Google's Flow objects
   which had to be re-created and carefully reused per login attempt.
   MSAL's own built-in token cache is deliberately NOT used here (it's a
   single shared cache object across every visitor, and correctly picking
   the right visitor's tokens back out of it is an easy way to leak one
   visitor's calendar into another's) -- tokens are pulled out immediately
   after acquisition and stored in the same per-session _sessions pattern
   used for Google.

2. No restricted "app-created calendars only" scope. Google's
   calendar.app.created scope makes it structurally impossible for this
   app to touch anything but calendars it created itself. Microsoft Graph
   has no scope that narrow -- the closest delegated permission,
   Calendars.ReadWrite, technically grants access to a visitor's ENTIRE
   calendar set. This module only ever creates and writes to its own
   dedicated "Syllabus Deadlines" calendar as a matter of this codebase's
   own convention, not because the OAuth scope enforces it. Say this
   plainly to users in the connect-panel copy, not just here.

Requires a one-time manual Azure app registration (see README) and
MICROSOFT_OAUTH_CLIENT_ID / MICROSOFT_OAUTH_CLIENT_SECRET environment
variables -- unlike Google, Azure has no downloadable "client secret JSON"
file to fall back to, so env vars are the only configuration path here.
"""

from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timedelta
from typing import Any

import msal
import requests

try:
    from tzlocal import get_localzone_name
except ImportError:  # pragma: no cover - tzlocal is a required dependency
    get_localzone_name = None  # type: ignore[assignment]


SCOPES = ["Calendars.ReadWrite", "offline_access", "User.Read"]
AUTHORITY = "https://login.microsoftonline.com/common"
REDIRECT_URI = os.getenv("MICROSOFT_OAUTH_REDIRECT_URI", "http://localhost:8000/auth/microsoft/callback")
CALENDAR_NAME = "Syllabus Deadlines"
EVENT_DURATION_MINUTES = 30
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# In-flight OAuth attempts, keyed by the CSRF "state" token this module
# mints itself (unlike Google's Flow, which returns state as part of
# building the authorization URL, MSAL's low-level API takes state as an
# input). Maps state -> session_id, so the callback knows which visitor a
# given login attempt belongs to. In-memory only.
_pending_states: dict[str, str] = {}

# Per-visitor credential storage, its own dict separate from Google's --
# a visitor could connect both providers in one session, and sharing one
# dict keyed only by session_id would let one provider's bucket clobber the
# other's calendar_id/tokens. Each bucket holds the raw MSAL token result
# plus a computed "expires_at" and a cached "calendar_id".
_sessions: dict[str, dict[str, Any]] = {}


class MicrosoftCalendarNotConfigured(Exception):
    """Raised when MICROSOFT_OAUTH_CLIENT_ID/SECRET aren't set."""


def _client_id() -> str | None:
    return os.getenv("MICROSOFT_OAUTH_CLIENT_ID")


def _client_secret() -> str | None:
    return os.getenv("MICROSOFT_OAUTH_CLIENT_SECRET")


def is_client_configured() -> bool:
    """Whether the Azure app registration's credentials are set via env vars.

    Unlike Google, there's no local-file fallback -- Azure App Registration
    has no downloadable "client_secret.json"-shaped artifact to save, so
    environment variables are the only configuration path.
    """
    return bool(_client_id() and _client_secret())


def _msal_app() -> msal.ConfidentialClientApplication:
    if not is_client_configured():
        raise MicrosoftCalendarNotConfigured(
            "Microsoft Calendar isn't set up yet. Set MICROSOFT_OAUTH_CLIENT_ID "
            "and MICROSOFT_OAUTH_CLIENT_SECRET (see setup instructions)."
        )
    # Built fresh from current env vars rather than cached at import time,
    # so a server that starts before these are set can still pick them up
    # once configured, without a restart.
    return msal.ConfidentialClientApplication(
        client_id=_client_id(),
        client_credential=_client_secret(),
        authority=AUTHORITY,
    )


def build_authorization_url(session_id: str) -> str:
    """Build the Microsoft consent-screen URL for a fresh login attempt."""
    state = secrets.token_urlsafe(32)
    _pending_states[state] = session_id
    return _msal_app().get_authorization_request_url(
        SCOPES,
        state=state,
        redirect_uri=REDIRECT_URI,
    )


def exchange_code_for_token(code: str, state: str) -> None:
    """Exchange the callback's auth code for tokens, stored under that visitor's session."""
    session_id = _pending_states.pop(state, None)
    if session_id is None:
        raise ValueError("Invalid or expired OAuth state (possible CSRF or stale link).")

    result = _msal_app().acquire_token_by_authorization_code(
        code,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    # MSAL returns errors in-band as a dict key rather than raising.
    if "error" in result:
        raise RuntimeError(result.get("error_description") or result["error"])

    _store_token_result(session_id, result)


def _store_token_result(session_id: str, result: dict[str, Any]) -> None:
    bucket = _sessions.setdefault(session_id, {})
    bucket["access_token"] = result["access_token"]
    # refresh_token is only present when offline_access was granted; keep
    # any previously stored one if this particular result omits it (some
    # refresh flows don't re-issue a new refresh_token).
    if "refresh_token" in result:
        bucket["refresh_token"] = result["refresh_token"]
    # MSAL gives expires_in (seconds from now), not an absolute time -- Google's
    # Credentials object tracks this automatically, MSAL's raw dict doesn't.
    bucket["expires_at"] = time.time() + result.get("expires_in", 0) - 60  # 60s safety buffer


def is_connected(session_id: str) -> bool:
    bucket = _sessions.get(session_id, {})
    return bool(bucket.get("refresh_token") or bucket.get("access_token"))


def disconnect(session_id: str) -> None:
    _sessions.pop(session_id, None)


def _get_access_token(session_id: str) -> str:
    bucket = _sessions.get(session_id, {})
    if not bucket.get("access_token") and not bucket.get("refresh_token"):
        raise RuntimeError("Microsoft Calendar isn't connected yet.")

    if bucket.get("expires_at", 0) > time.time():
        return bucket["access_token"]

    refresh_token = bucket.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("Microsoft Calendar session expired. Please reconnect.")

    result = _msal_app().acquire_token_by_refresh_token(refresh_token, scopes=SCOPES)
    if "error" in result:
        raise RuntimeError(result.get("error_description") or result["error"])

    _store_token_result(session_id, result)
    return _sessions[session_id]["access_token"]


def _local_timezone() -> str:
    if get_localzone_name is not None:
        try:
            name = get_localzone_name()
            if name:
                return name
        except Exception:
            pass
    return "UTC"


def _graph_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}


def _get_or_create_calendar_id(session_id: str, access_token: str) -> str:
    """Return this visitor's dedicated calendar id, creating it on first use.

    Note: unlike the Google client, there's no scope-level restriction
    forcing this discipline -- Calendars.ReadWrite technically permits
    listing/reading every calendar the visitor has. This app simply never
    does that, by its own convention, always confining itself to the one
    dedicated calendar it creates.
    """
    bucket = _sessions.setdefault(session_id, {})
    cached_id = bucket.get("calendar_id")
    if cached_id:
        resp = requests.get(f"{GRAPH_BASE}/me/calendars/{cached_id}", headers=_graph_headers(access_token))
        if resp.ok:
            return cached_id

    resp = requests.post(
        f"{GRAPH_BASE}/me/calendars",
        headers=_graph_headers(access_token),
        json={"name": CALENDAR_NAME},
    )
    resp.raise_for_status()
    calendar_id = resp.json()["id"]
    bucket["calendar_id"] = calendar_id
    return calendar_id


def _build_event_body(event: dict[str, str], timezone: str) -> dict[str, Any]:
    due_date = event.get("due_date", "")
    due_time = event.get("due_time", "23:59")
    start_dt = datetime.strptime(f"{due_date} {due_time}", "%Y-%m-%d %H:%M")
    end_dt = start_dt + timedelta(minutes=EVENT_DURATION_MINUTES)

    course_name = (event.get("course_name") or "").strip()
    task_name = (event.get("task_name") or "").strip()
    subject = f"{course_name} - {task_name}" if course_name and task_name else (course_name or task_name)

    return {
        "subject": subject,
        "body": {"contentType": "text", "content": event.get("description", "")},
        "start": {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": timezone},
        "end": {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": timezone},
    }


def push_events(events: list[dict[str, str]], session_id: str) -> dict[str, Any]:
    """Push events into this visitor's dedicated "Syllabus Deadlines" calendar.

    Returns {"created": N, "failed": [{"event": ..., "error": ...}, ...],
    "calendar_id": ..., "calendar_html_link": ...}. Never raises on a
    per-event failure — one bad event shouldn't sink the whole batch.
    """
    access_token = _get_access_token(session_id)
    calendar_id = _get_or_create_calendar_id(session_id, access_token)
    timezone = _local_timezone()

    created = 0
    failed: list[dict[str, str]] = []
    for event in events:
        try:
            body = _build_event_body(event, timezone)
            resp = requests.post(
                f"{GRAPH_BASE}/me/calendars/{calendar_id}/events",
                headers=_graph_headers(access_token),
                json=body,
            )
            resp.raise_for_status()
            created += 1
        except Exception as exc:
            failed.append({"event": event.get("task_name", "Untitled event"), "error": str(exc)})

    return {
        "created": created,
        "failed": failed,
        "calendar_id": calendar_id,
        # Graph has no documented deep-link scheme to jump straight to a
        # specific calendar by id the way Google's calendar.google.com/r
        # does -- this just opens the general Outlook web calendar view.
        "calendar_html_link": "https://outlook.office.com/calendar/view/month",
    }
