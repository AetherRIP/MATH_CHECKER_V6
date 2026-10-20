# Math Checker V6 — Configuration Reference

All configuration is environment-driven (`MC6_*`). The authoritative variable
list lives in [.env.example](.env.example) (placeholders only — committed) and
the setup walkthrough in [README.md](README.md); this document records the
operational rules that apply to every host.

## Rules

1. **Precedence:** a variable already present in the process environment
   always wins over `.env`. The `.env` file lives in the project root; a real
   `.env` is git-ignored, only the placeholder [.env.example](.env.example) is
   committed. Never put real credentials in it or in any committed file.
2. **Secrets are server-side only.** `MC6_AI_API_KEY` and the Classroom OAuth
   client JSON are never logged (error messages name variables, never values),
   never returned by any API response, never embedded in browser storage or
   the frontend bundle. Classroom refresh tokens are written under
   `<MC6_DATA_DIR>/secrets/`, which is inside the git-ignored data directory.
3. **Restart required for corrections config.** `MC6_AI_API_KEY`, `MC6_AI_MODEL`,
   `MC6_AI_BASE_URL`, `MC6_AI_TIMEOUT_SECONDS`, `MC6_AI_MAX_RETRIES` and
   `MC6_GOOGLE_OAUTH_CLIENT` are read once at startup. Changing them needs a
   process restart. Runtime-editable server settings (`max_upload_mb`,
   `default_feedback_detail`) are stored in SQLite via `/api/settings` and do
   NOT need a restart.
4. **Validation and failure handling.** Invalid optional values raise a
   `ConfigError` at startup with a message naming the variable but never its
   value (example: `MC6_AI_TIMEOUT_SECONDS must be between 5 and 600.`). If
   the database cannot initialize the app still starts degraded: the UI and
   `/api/health` work, data routes answer `503 database_unavailable`.
5. **Data location.** Everything persistent lives under `MC6_DATA_DIR`
   (default `./data`): `app.db` (WAL SQLite), `uploads/<job_id>` workspaces
   (temporary, removed at every terminal state), `tmp/`, `reports/`, `cache/`,
   `secrets/`. Point this one variable at a persistent volume on any host.
6. **Network defaults.** Host `127.0.0.1`, port `8643`. Explicit opt-in is
   required to listen on all interfaces (`--host 0.0.0.0` or `MC6_HOST`), which
   is expected only behind a trusted proxy. An occupied port is detected
   before launch: the process exits 1 with a clear message instead of a
   traceback.

## Provider limits (honest)

No unlimited free AI usage is promised. The engine bounds itself to 2
concurrent provider calls per process and retries only transient failures
(429, 5xx, transport) with exponential backoff capped at 8 s, at most
`MC6_AI_MAX_RETRIES` (0–5, default 2) times. A permanent failure (401/403/404)
fails the job immediately with a safe message; nothing is silently retried
into a fabricated result. Inline uploads are capped at 12 MiB raw per request
(the engine leaves out oversized visuals and says so).
