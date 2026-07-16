# Syllabus to Calendar

Upload a syllabus (PDF, TXT, or MD) and get every exam, quiz, and assignment
deadline extracted automatically and marked on a calendar — Google Calendar
directly, or a universal `.ics` file for Apple Calendar / Outlook / anything
else.

## How it works

```
Upload syllabus (or add an event by hand)
    -> extract text (PyMuPDF for PDF, plain read for TXT/MD)
    -> Gemini extracts course/task/date/time/description as JSON
    -> validated & normalized (dates -> YYYY-MM-DD, times -> HH:MM)
    -> review & edit extracted events in the browser
    -> choose a destination: Google Calendar / Apple Calendar / Device
    -> Google: pushed directly via OAuth into a dedicated calendar
       Apple/Device: download a ready-to-import .ics file
```

The whole pipeline runs locally: a FastAPI backend on `localhost:8000` and a
single static `index.html` frontend (no build step, no framework).

## Setup

### 1. Install dependencies

```
pip install -r requirements.txt
```

### 2. Configure your Gemini API key

Create a `.env` file in the project root:

```
GOOGLE_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-flash-lite-latest
```

`GEMINI_MODEL` is optional (defaults to `gemini-2.0-flash`) but worth
setting explicitly — some pinned model versions can return `429` with zero
free-tier quota depending on your Google Cloud project, while `-latest`
alias models tend to have quota available. If you hit quota errors, try
`gemini-flash-lite-latest`, `gemini-3-flash-preview`, or check
`client.models.list()` for what's available to your key.

### 3. (Optional) Set up Google Calendar push

Only needed if you want the "Google Calendar" destination to work — Apple
Calendar and Device/Other work with zero setup via the `.ics` download.

1. [Google Cloud Console](https://console.cloud.google.com) → **APIs &
   Services → Library** → enable **Google Calendar API**.
2. **APIs & Services → OAuth consent screen** → User type **External** →
   fill the required fields → add your Google account under **Test users**.
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
   → Application type **Web application** → Authorized redirect URI:
   `http://localhost:8000/auth/google/callback` → Create.
4. Download the client JSON and save it as `.secrets/client_secret.json` in
   the project root (create the folder if it doesn't exist — it's
   gitignored, same as `.env`).

Events are pushed into a dedicated **"Syllabus Deadlines"** calendar (not
your primary calendar) using the restricted `calendar.app.created` OAuth
scope, so this app never has access to your existing calendars or events —
only the ones it creates itself.

### 4. Run it

```
uvicorn server.main:app --reload --port 8000
```

Then open `http://localhost:8000/` in a browser — the backend serves the
frontend itself, so there's no separate file to open.

## Hosting it for multiple people

The app is built to be safely hosted for concurrent public users (session-
scoped Google credentials, a rate limiter protecting the shared Gemini key,
configurable CORS/redirect URIs) — see `DEPLOYMENT.md` for the full
walkthrough.

## Project layout

| Path | Purpose |
|------|---------|
| `src/ingest/file_ingestor.py` | Extracts text from PDF/TXT/MD |
| `src/ai/gemini_pipeline_controller.py` | Builds the extraction prompt, calls Gemini |
| `src/validation/string_validator.py` | Parses/normalizes Gemini's JSON into event dicts |
| `src/export/icalendar_factory.py` | Builds RFC-5545 `.ics` calendar files |
| `src/calendar_push/google_calendar_client.py` | Google OAuth + pushes events into Calendar API |
| `server/main.py` | FastAPI backend: streaming `/process`, `/download`, `/auth/google/*`, `/calendar/google/push` |
| `index.html` | The whole frontend — 5-step wizard, vanilla JS + Tailwind CDN |
| `main.py` | CLI runner for the core pipeline (no web server, no calendar push) |

## Notes on the design

- **No database, no stored user data.** The app processes a syllabus and
  hands you an outcome (a pushed calendar or a downloaded file) — it
  doesn't keep your syllabus text, extracted events, or personal
  information after your session. Google OAuth credentials are held
  in-memory only, keyed by an opaque per-visitor session cookie — nothing
  is ever written to disk per-user, and everyone's session clears on a
  server restart. This also means each visitor re-authenticates with
  Google each session rather than staying signed in indefinitely — a
  deliberate tradeoff, not a limitation.
- **Real-time status, not a fake progress bar.** `/process` streams actual
  per-phase progress via Server-Sent Events as the pipeline runs
  (extract → Gemini → validate), rather than simulating one with timers.
- **Missing data doesn't fail the whole batch.** An event Gemini couldn't
  confidently extract a course/task/date for is flagged `incomplete`
  instead of aborting the entire upload — fix it by hand on the Review step.
- **Apple Calendar has no OAuth push equivalent.** There's no public API for
  third-party apps to write directly into iCloud Calendar the way Google's
  Calendar API allows — the `.ics` download is the actual idiomatic
  integration path, since Apple Calendar imports `.ics` natively.
