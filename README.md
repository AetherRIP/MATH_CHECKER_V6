# Math Checker V6 — Phase 3

A lightweight, modular application for correcting Edexcel IGCSE Mathematics
homework with AI, generating reports, and (in later phases) integrating with
Google Classroom.

**Phase 1 delivered the interface.** **Phase 2 delivered the backend
foundation** (SQLite behind one storage boundary, settings, honest status
endpoints, live UI wiring). **Phase 3 delivers the mathematical correction
engine**: document validation, PDF extraction, mark-scheme interpretation by a
configured AI provider, question-level marking, deterministic result
validation, totals and explicit uncertainty.

The engine is complete and independently testable, but it is not yet wired to
the browser: uploading, job persistence and result display are **Phase 4**.
Nothing in the interface pretends otherwise.

---

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+ · FastAPI · uvicorn (3 runtime dependencies, including `pypdf`) |
| Storage | SQLite via the standard-library `sqlite3` module — **no ORM, no migration package** |
| AI provider | Gemini REST API through standard-library `urllib` — **no provider SDK** |
| Frontend | Vanilla HTML/CSS/ES modules — **no build step, no Node toolchain needed to run** |
| Routing | Hash routes (`/#/dashboard`) — every page is directly navigable |

## Requirements

- Python 3.11 or newer (developed and tested on 3.14)
- An API key for the configured AI provider **to run corrections**
- Node.js 20+ **only if you want to run the frontend unit tests** — not needed to run the app

## Setup

```bash
cd MATH_CHECKER_V6
python -m venv .venv

# Windows (Git Bash / PowerShell):
.venv/Scripts/python -m pip install -r requirements-dev.txt
# macOS / Linux:
#   .venv/bin/python -m pip install -r requirements-dev.txt
```

For a deployment that only needs to run, `requirements.txt` is enough. It now
includes `pypdf`, used by the engine to validate and extract PDF text.

## Launch

```bash
.venv/Scripts/python main.py
```

Then open **http://127.0.0.1:8643**. Without an AI key the application runs
normally, reports the correction engine as unavailable, and refuses to invent
results.

```bash
python main.py --port 9000       # override the port
python main.py --host 0.0.0.0    # listen on all interfaces (explicit opt-in)
python main.py --version         # print the version and exit
python main.py --seed-dev        # insert deterministic development data and exit
```

Configuration is environment-driven (see `.env.example`). Values already
present in the process environment always win over `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `MC6_HOST` | `127.0.0.1` | interface to bind (private by default) |
| `MC6_PORT` | `8643` | TCP port |
| `MC6_DEBUG` | `0` | `1` enables verbose logging |
| `MC6_LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` |
| `MC6_DATA_DIR` | `./data` | application data directory; the SQLite database lives here |
| `MC6_TMP_DIR` | `<data>/tmp` | temporary directory used by Phase 4 job workspaces |
| `MC6_AI_API_KEY` | — | **enables correction**; server-side only |
| `MC6_AI_MODEL` | `gemini-2.5-flash` | model used for marking |
| `MC6_AI_BASE_URL` | `https://generativelanguage.googleapis.com` | provider endpoint |
| `MC6_AI_TIMEOUT_SECONDS` | `180` | per-request timeout (5–600) |
| `MC6_AI_MAX_RETRIES` | `2` | transient retries (0–5) |

Never commit a filled-in `.env`. The key is never logged, returned by an API,
or sent to the browser.

## Correction engine (Phase 3)

The engine is reachable through `backend/app/engine.py` and implemented in
`backend/app/correction/`. The full behavioral contract is
[`docs/correction-engine-contract.md`](docs/correction-engine-contract.md).

Pipeline:

```
validate request → validate/extract documents → mark-scheme blueprint →
provider marking → strict JSON parse → mark/maximum validation →
deterministic answer checks → typed report
```

What it does:

- Rejects missing, empty, corrupt, encrypted, mislabelled or oversized files
  before any provider call.
- Extracts PDF text with page numbers; reports pages with no extractable text
  instead of treating them as blank answers.
- Requires a mark scheme (file and/or pasted text) and extracts a conservative
  question/maximum blueprint from it.
- Sends the student work and mark scheme to the configured model, asking for
  one question-level result per label with evidence, criteria and explicit
  uncertainty.
- Rejects impossible output: duplicate labels, missing marks, text instead of
  numbers, negative marks, or marks above the question maximum.
- Recomputes totals and percentages in Python. A partial result never carries
  a misleading percentage.
- Turns a question the model did not return into `unresolved`, never `0`.
- Runs deterministic numeric/fraction/percentage/expression checks and flags
  contradictions for review **without changing a mark**.
- Retries transient provider failures a bounded number of times and gives one
  bounded JSON-repair attempt. Failures produce a failed job with a safe
  message, never an empty "success".

What it does **not** do yet:

- upload files from the browser, persist jobs, or display results (Phase 4);
- independently apply M/A/B/ECF rules in Python — those judgements are made by
  the model from the mark scheme;
- generate report files or Edexcel grades;
- contact Google Classroom.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | liveness probe (`{"status": "ok"}`) |
| `GET /api/system/status` | version, phase, database readiness, live engine state and honest feature flags |
| `GET /api/settings` | current server settings |
| `PATCH /api/settings` | update `max_upload_mb` and/or `default_feedback_detail` |
| `GET /api/database/stats` | student/assignment/submission/correction counts |
| `GET /api/storage/summary` | real, bounded measurement of the application data directory |
| `GET /api/openapi.json` | OpenAPI document (the CDN-backed docs UIs are disabled) |

Every API failure uses the same envelope:

```json
{
  "error": {
    "code": "invalid_request",
    "message": "…",
    "request_id": "…"
  }
}
```

`/api/system/status` reports the live engine
(`correction_engine.available`, `.name`, `.reason`) and sets
`features.ai_correction` / `features.grade_submission` from it.
`pdf_processing` is true because extraction is implemented. `reports` and
`background_tasks` remain false until Phase 4.

If the database cannot initialize, the app starts degraded: the UI and
`/api/health` still work, `/api/system/status` reports
`database.status: "unavailable"`, and data endpoints return a `503`
`database_unavailable` envelope.

## Database and settings

- Schema version 1 lives in `backend/app/migrations/001_initial.sql` and is
  applied through `PRAGMA user_version` by `backend/app/db.py`.
- Tables: `students`, `assignments`, `submissions`, `correction_results`,
  `settings`. Phase 3 adds **no** tables; durable correction jobs and
  question items arrive with Phase 4 as migration `002`.
- Missing, draft, submitted, graded and failed work are distinct states; a
  zero mark is stored as a real `0`, not as “no result”.
- Lesson codes are stored exactly as entered (`CH1L1`, `CH1L13`).
- Server settings are operational only: `max_upload_mb` (1–25) and
  `default_feedback_detail` (`brief`/`detailed`). Browser preferences remain
  in `localStorage`.

Development fixtures are explicit and idempotent:

```bash
.venv/Scripts/python main.py --seed-dev
```

They create two students, two assignments, four submissions and one completed
zero-mark correction. Nothing is inserted automatically.

## Testing

Backend (pytest):

```bash
PYTHONPATH=backend .venv/Scripts/python -m pytest backend/tests -q
```

Frontend (Node's built-in test runner — zero packages to install):

```bash
cd frontend && npm test
# equivalent: node --test "tests/*.test.mjs"
```

Tests never contact an external AI provider. Provider behaviour is tested
against a local HTTP stub, and engine orchestration uses a deterministic fake
model client. That means the suite verifies the pipeline, validation and
failure handling — **not** the live model's marking accuracy.

## Project structure

```
MATH_CHECKER_V6/
├── main.py                      # launcher: config → uvicorn
├── requirements.txt             # fastapi, uvicorn, pypdf
├── requirements-dev.txt         # + pytest, httpx
├── .env.example                 # configuration template (placeholders only)
├── backend/
│   ├── app/
│   │   ├── config.py            # MC6_* env vars, database_path, AI config
│   │   ├── logging_setup.py     # application logger + request-id context
│   │   ├── db.py                # connections, PRAGMAs, migration runner
│   │   ├── migrations/          # numbered SQL schema files
│   │   ├── models.py            # dataclasses, enums, settings definitions
│   │   ├── storage.py           # the only SQL boundary
│   │   ├── services.py          # settings and statistics services
│   │   ├── engine.py            # engine contract + get_engine()
│   │   ├── correction/          # Phase 3 engine (documents, scheme, prompts,
│   │   │                        # provider, parsing, validation, verify, service)
│   │   ├── main.py              # FastAPI app, lifecycle, static serving
│   │   └── api/                 # system, settings, database, storage routers
│   └── tests/                   # pytest suite (incl. PDF factory + provider stub)
├── frontend/                    # zero-build vanilla SPA
└── docs/
    ├── architecture.md
    ├── correction-engine-contract.md
    ├── phase-1-report.md
    ├── phase-2-report.md
    ├── phase-3-report.md
    └── screenshots/
```

## What works today

- Complete application shell and five pages, all directly navigable.
- Dashboard: real database counts, submission-status breakdown, and readiness
  that reads the live engine flag (not a hardcoded promise).
- Settings: real server settings, browser preferences, live diagnostics.
- Correction page: file selection, validation, review and options draft; the
  Start action remains disabled with an honest Phase 4 explanation.
- Storage: real, on-request measurement of the application data directory.
- Task Manager: planned categories with honest empty states.
- Correction engine: the full Phase 3 pipeline above, independently testable.

## Not in Phase 3

Upload endpoints and durable jobs · browser result display · report files ·
Classroom sync · classes/rosters · authentication · a distributed worker
system · a second database or configuration system · a UI redesign.

## Troubleshooting

**Correction is unavailable**
Set `MC6_AI_API_KEY` (and optionally `MC6_AI_MODEL`) in the server environment
or `.env`, then restart. The UI shows the engine's reason rather than failing
silently.

**`MC6_AI_TIMEOUT_SECONDS must be an integer` / similar**
An optional provider setting has an invalid value. Fix or remove it; the error
never prints the key.

**Port 8643 is already in use**
Start on another one: `python main.py --port 8650`.

**A PDF is rejected**
The engine validates bytes, page structure and encryption. Password-protected
or corrupt files must be unlocked/re-exported. A scanned PDF with no text is
accepted but flagged; it relies on the provider's visual reading.

**The page loads but looks like an older version**
The frontend is plain files; hard-refresh (Ctrl+Shift+R) after replacing them.

**Where are my files stored?**
Runtime data lives under `data/` (or `MC6_DATA_DIR`). The SQLite database is
`app.db` inside it.

## License

See the repository's license file.
