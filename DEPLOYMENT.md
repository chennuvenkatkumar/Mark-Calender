# Deploying (hosted, multi-user)

The app is code-ready to host publicly: session-scoped Google
OAuth (no database — see README's "Notes on the design"), a rate limiter
protecting the shared Gemini key, and CORS/frontend serving that work off a
single configurable origin. This doc covers the one part that's on you:
standing up an actual host.

## Recommended: Render

Free/cheap tier, deploys straight from this GitHub repo, gives a real HTTPS
URL with no extra config. `render.yaml` in the repo root is a ready-to-use
Blueprint — Render will read it automatically if you deploy via
**New → Blueprint** and point it at this repo. Railway, Fly.io, or any
similar host work too (the `Procfile` covers those); nothing here is
Render-specific at the code level.

## Steps

1. **Create the account and connect the repo.** Render → New → Blueprint (or
   Web Service, if not using `render.yaml`) → connect this GitHub repo →
   branch `I1code`.
2. **Set environment variables** in the platform's dashboard (never commit
   these — they're separate from the gitignored local `.secrets/` folder,
   which stays local-dev-only):

   | Variable | Value |
   |---|---|
   | `GOOGLE_API_KEY` | Your Gemini API key |
   | `GEMINI_MODEL` | Optional, e.g. `gemini-flash-lite-latest` |
   | `GOOGLE_OAUTH_CLIENT_ID` | From the same OAuth client JSON you downloaded for local dev |
   | `GOOGLE_OAUTH_CLIENT_SECRET` | Same source |
   | `SESSION_SECRET_KEY` | Random value — generate once via `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
   | `SESSION_HTTPS_ONLY` | `true` (cookies only sent over HTTPS in production) |
   | `OAUTH_REDIRECT_URI` | `https://<your-app-url>/auth/google/callback` |
   | `ALLOWED_ORIGIN` | `https://<your-app-url>` |
   | `GEMINI_MAX_CONCURRENT` | Optional, default `3` |
   | `GEMINI_MAX_PER_MINUTE` | Optional, default `15` |

3. **Deploy**, then note the real HTTPS URL Render assigns (e.g.
   `https://mark-calender.onrender.com`).
4. **Add the production redirect URI in Google Cloud Console** — go to the
   *same* OAuth client you already created for local dev → **Authorized
   redirect URIs** → add
   `https://<your-app-url>/auth/google/callback` as a **second** entry,
   alongside the existing `http://localhost:8000/auth/google/callback`.
   Both coexist fine on one client — local dev keeps working after this.
5. Update `OAUTH_REDIRECT_URI` and `ALLOWED_ORIGIN` (step 2) to match the
   real URL once you have it, and redeploy if you set them before knowing
   the final URL.

## Known caveats

- **Free-tier spin-down.** Free tiers on Render/Railway/Fly.io typically
  sleep the server after inactivity — the first request after idling will
  be slow (cold start). Fine for testing; a paid "always on" tier (usually
  ~$5-7/month) is worth it once this sees real regular traffic.
- **In-memory session/rate-limit state resets on every restart or
  redeploy** — by design (see README). Everyone currently mid-session has
  to reconnect Google and re-upload if the server restarts. This is a
  deliberate tradeoff, not a bug, matching the app's "don't retain user
  data" philosophy.
- **Single process only.** The in-memory session store and rate limiter
  only work correctly with one server process (`--workers 1`, which is the
  default on these platforms for a service this size). Don't scale this
  past one instance without redesigning session storage — doing so would
  likely require a shared store (e.g. Redis), which conflicts with the
  "no database" constraint, so it hasn't been built.
