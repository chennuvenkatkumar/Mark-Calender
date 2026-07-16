# Syllabus-to-Calendar Frontend — User Guide

## Quick Start

Run the backend (`uvicorn server.main:app --reload --port 8000`), then open
`http://localhost:8000/` in a browser — the backend serves the frontend
itself.

## The 5-step flow

### Step 1: Upload
- Drag & drop a file onto the upload zone, or click it / "Choose file" to browse.
- Supported: PDF, TXT, MD (max 20 MB).
- No syllabus handy? Click **"+ Add an event manually"** below the upload
  zone instead — it drops you straight into the Review step with one blank
  event ready to fill in. The PDF upload stays the primary path; this is a
  secondary option for quick one-off entries.

### Step 2: Processing (real, live status)
A checklist shows each pipeline phase as it actually happens on the server
— not a simulated timer:
1. Extracting text
2. Analyzing with Gemini AI
3. Validating & normalizing

Each step animates (spinner → checkmark) as the backend streams its real
progress, with an elapsed-time counter. If anything fails, a specific error
message appears and you're returned to Upload — never a silent stall.

### Step 3: Review & edit
Every extracted event is an editable card: course, task, due date/time, and
description. Edits apply live, no save button needed.

- Cards with a missing course, task, or date show an amber **"needs info"**
  tag — the extraction pipeline flags rather than silently drops these, so
  you can fill them in by hand.
- The **"Choose calendar →"** button is disabled (with an inline message)
  until every incomplete event is fixed or removed.
- **"+ Add event"** creates another blank card, pre-filled with the same
  course name as the first event for convenience.

### Step 4: Choose your calendar
Pick a destination:

- **Google Calendar** — pushes events directly via your Google account into
  a dedicated "Syllabus Deadlines" calendar (your existing calendars are
  never touched or even visible to this app). First use opens a Google
  sign-in popup; after that it just pushes.
- **Apple Calendar** — downloads an `.ics` file; double-click it and it
  opens straight into Calendar on Mac/iOS.
- **Device / Other** — same universal `.ics` file, for Outlook, Yahoo
  Calendar, Windows Calendar, Thunderbird, etc.

### Step 5: Done
Confirms what happened (events pushed to Google, or a file downloaded) with
a destination-appropriate summary, plus a **"Process another syllabus"**
button to reset and start over.

## Troubleshooting

**"Cannot connect to the server"** — the FastAPI backend isn't running.
Start it with `uvicorn server.main:app --reload --port 8000`.

**AI step fails / quota errors** — the Gemini free tier is rate-limited; the
error banner tells you exactly what happened (rate limit, timeout, empty
response) with a specific tip. If it persists, check `GEMINI_MODEL` in
`.env` — some pinned model versions can have zero quota on certain Google
Cloud projects even when the model name itself is valid.

**Some events show "needs info"** — Gemini couldn't confidently extract a
course, task, or date for that item. Fill it in manually or delete it; you
can't continue to the Calendar step until it's resolved.

**Google Calendar option won't connect** — the app needs a one-time Cloud
Console setup (see `README.md`). Until `.secrets/client_secret.json` exists,
the app tells you so explicitly rather than failing silently.

**Can't import the downloaded file** — confirm it actually downloaded, and
that your calendar app supports `.ics` import (virtually all do).
