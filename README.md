# Math Checker V6 — Phase 2

A lightweight, modular application for correcting Edexcel IGCSE Mathematics
homework with AI, generating reports, and (in later phases) integrating with
Google Classroom.

**Phase 1 delivered the foundation:** a dark-themed interface, shared
application shell, reusable components and five working pages.

**Phase 2 delivers the backend foundation:** a local SQLite database behind a
single storage boundary, typed settings, honest health/status endpoints,
consistent error handling, deterministic development fixtures, and a UI that
reads live backend data instead of hardcoded placeholders.

The application runs and is fully useful **without any AI key or credential**.
AI correction itself is **Phase 3**.

---

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+ · FastAPI · uvicorn (2 runtime dependencies) |
| Storage | SQLite via the standard-library `sqlite3` module — **no ORM, no migration package** |
| Frontend | Vanilla HTML/CSS/ES modules — **no build step, no Node toolchain needed to run** |
| Routing | Hash routes (`/#/dashboard`) — every page is directly navigable |

## Requirements

- Python 3.11 or newer (developed and tested on 3.14)
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

Use `requirements-dev.txt` for development (it includes the test tools).
For a deployment that only needs to run, `requirements.txt` is enough:

```bash
.venv/Scripts/python -m pip install -r requirements.txt
```

## Launch

```bash
.venv/Scripts/python main.py
```

Then open **http://127.0.0.1:8643** in a browser.

Options:

```bash
python main.py --port 9000       # override the port
python main.py --host 0.0.0.0    # listen on all interfaces (explicit opt-in)
python main.py --version         # print the version and exit
python main.py --seed-dev        # insert deterministic development data and exit
```

On first start the application creates its data directory and the SQLite
database (`app.db`) inside it. No AI or Google credentials are required.

Configuration is environment-driven (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `MC6_HOST` | `127.0.0.1` | interface to bind (private by default) |
| `MC6_PORT` | `8643` | TCP port |
| `MC6_DEBUG` | `0` | `1` enables verbose logging |
| `MC6_LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` |
| `MC6_DATA_DIR` | `./data` | application data directory; the SQLite database lives here |
| `MC6_TMP_DIR` | `<data>/tmp` | temporary processing directory |

To use a `.env` file, copy the template:

```bash
cp .env.example .env   # then edit; real values never belong in .env.example
```

Values already present in the process environment always win over `.env`.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | liveness probe (`{"status": "ok"}`) |
| `GET /api/system/status` | version, phase, database readiness and honest feature flags |
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

If the database cannot initialize, the app starts degraded: the UI and
`/api/health` still work, `/api/system/status` reports
`database.status: "unavailable"`, and data endpoints return a `503`
`database_unavailable` envelope.

## Database and settings

- Schema version 1 lives in `backend/app/migrations/001_initial.sql` and is
  applied through `PRAGMA user_version` by `backend/app/db.py`.
- Tables: `students`, `assignments`, `submissions`, `correction_results`,
  `settings`.
- Missing, draft, submitted, graded and failed work are distinct states; a
  zero mark is stored as a real `0`, not as “no result”.
- Lesson codes are stored exactly as entered (`CH1L1`, `CH1L13`).
- Server settings are operational only: `max_upload_mb` (1–25) and
  `default_feedback_detail` (`brief`/`detailed`). Browser preferences
  (start page, density, confirmation) remain in `localStorage`.

Development fixtures are explicit and idempotent:

```bash
PYTHONPATH=backend .venv/Scripts/python -m app.dev_fixtures
# or
.venv/Scripts/python main.py --seed-dev
```

They create two students, two assignments (`CH1L1`, `CH1L13`), four
submissions covering missing/draft/submitted/graded, and one completed
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

## Project structure

```
MATH_CHECKER_V6/
├── main.py                  # launcher: config → uvicorn, --version, --seed-dev
├── requirements.txt         # 2 runtime dependencies
├── requirements-dev.txt     # + pytest, httpx
├── .env.example             # configuration template (placeholders only)
├── backend/
│   ├── app/
│   │   ├── config.py        # MC6_* env vars + database_path + .env loader
│   │   ├── logging_setup.py # application logger + request-id context
│   │   ├── db.py            # connections, PRAGMAs, migration runner, status
│   │   ├── migrations/      # numbered SQL schema files
│   │   ├── models.py        # dataclasses, enums, settings definitions
│   │   ├── storage.py       # the only SQL boundary
│   │   ├── services.py      # settings and statistics services
│   │   ├── dev_fixtures.py  # deterministic, idempotent development seed
│   │   ├── engine.py        # Phase 3 engine contract + honest stub
│   │   ├── main.py          # FastAPI app, lifecycle, middleware, static serving
│   │   └── api/             # system, settings, database, storage routers
│   └── tests/               # pytest suite
├── frontend/
│   ├── index.html           # app shell document
│   ├── css/                 # tokens.css → base/layout/components
│   ├── js/
│   │   ├── main.js          # bootstrap
│   │   ├── router.js        # hash router (pages load on demand)
│   │   ├── api.js           # service layer — the integration seam
│   │   ├── store.js         # UI preferences (localStorage, harmless data only)
│   │   ├── ui/              # reusable components
│   │   ├── layout/shell.js  # sidebar + top bar + content slot
│   │   └── pages/           # dashboard, correction, settings, storage, tasks, notfound
│   └── tests/               # node --test suite
└── docs/
    ├── architecture.md             # design decisions and extension points
    ├── correction-engine-contract.md # Phase 3 engine contract
    ├── phase-1-report.md           # Phase 1 implementation report
    ├── phase-2-report.md           # Phase 2 implementation report
    └── screenshots/                # verified UI captures
```

## What works in Phase 2

- Complete application shell: collapsible sidebar, top bar, mobile drawer,
  and a version/phase label read live from the backend status response
- Five pages + a deliberate not-found page, all directly navigable
- Dashboard: real student, assignment, submission and correction counts read
  from the local database, submission-status breakdown, and a readiness panel
  that reports the live database state
- Settings: real server settings loaded and saved through the API (with
  loading/error states), browser preferences that really persist, and live
  backend/database diagnostics
- AI Correction: client-side file selection with validation, review/remove
  with confirmation, assignment/options draft, and an upload limit that
  follows the server setting; the Start button stays disabled with an
  explanation
- Storage: real, on-request measurements of the application data directory
  (including the SQLite database)
- Task Manager: the planned task categories with honest empty states
- Degraded startup: a broken database never takes the UI or health check down

## What is deliberately NOT in Phase 2

AI correction logic · Gemini/other provider integration · PDF extraction ·
mark-scheme verification · grading · Google Classroom sync · report
generation · background workers · authentication · classes/rosters ·
deployment automation. The UI marks each as planned; nothing pretends to
work. The AI correction engine is **Phase 3** and its contract is documented
in `docs/correction-engine-contract.md`.

## Troubleshooting

**`python main.py` says "Configuration error: MC6_PORT must be an integer"**
A `.env` file or environment variable sets `MC6_PORT` to a non-numeric value.
Fix or remove it.

**Port 8643 is already in use**
Another application (perhaps a previous instance) holds the port. Start on
another one: `python main.py --port 8650`.

**The status chip says the server is unreachable**
The frontend is being served but the API is not answering. Check the server
console for the database initialization error; the app intentionally keeps
serving the UI in this state.

**"No AI provider is configured" note at startup**
Normal — the whole interface works without one until Phase 3.

**The page loads but looks like an older version**
The frontend is served as plain files; do a hard refresh (Ctrl+Shift+R) after
replacing files so the browser drops cached modules.

**Frontend tests fail to start with "Cannot find module"**
Run them via the documented command (`npm test` inside `frontend/`); on some
Windows shells `node --test tests/` (directory form) is not resolved; the glob
form used by the script works everywhere tested.

**Where are my files stored?**
Runtime data lives under `data/` (or `MC6_DATA_DIR`). The SQLite database is
`app.db` inside that directory, so moving the directory moves the data.

## License

See the repository's license file.
