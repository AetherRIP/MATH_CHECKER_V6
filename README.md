# Math Checker V6 — Release (Phase 6)

A lightweight, modular application for correcting Edexcel IGCSE Mathematics
homework with AI, inspecting persisted question-level results, and
synchronising marks and correction reports with Google Classroom.

**Phase 1 delivered the interface.** **Phase 2 delivered the backend
foundation** (SQLite behind one storage boundary, settings, honest status
endpoints, live UI wiring). **Phase 3 delivered the mathematical correction
engine.** **Phase 4 connected them**: a browser upload creates a durable
correction job, the real Phase 3 engine marks the work, validated results are
stored atomically in SQLite, and the same result is readable after a refresh
or application restart. **Phase 5 verified the whole system end-to-end**
(audit, reliability fixes, a reproducible E2E walkthrough). **Phase 6 verified
integration and prepared release configuration.**

---

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+ · FastAPI · uvicorn · python-multipart · pypdf |
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

For a deployment that only needs to run, `requirements.txt` is enough.
`python-multipart` parses browser uploads and `pypdf` validates/extracts PDFs.

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
present in the process environment always win over `.env`. The correction
engine and job service are constructed **once at startup**, so changing
provider settings requires a restart.

| Variable | Default | Purpose |
|---|---|---|
| `MC6_HOST` | `127.0.0.1` | interface to bind (private by default) |
| `MC6_PORT` | `8643` | TCP port |
| `MC6_DEBUG` | `0` | `1` enables verbose logging |
| `MC6_LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` |
| `MC6_DATA_DIR` | `./data` | application data directory; SQLite and upload workspaces live here |
| `MC6_TMP_DIR` | `<data>/tmp` | application temporary directory |
| `MC6_AI_API_KEY` | — | **enables correction**; server-side only |
| `MC6_AI_MODEL` | `gemini-3.5-flash-lite` | model used for marking |
| `MC6_AI_BASE_URL` | `https://generativelanguage.googleapis.com` | provider endpoint |
| `MC6_AI_TIMEOUT_SECONDS` | `180` | per-request timeout (5–600) |
| `MC6_AI_MAX_RETRIES` | `2` | transient retries (0–5) |

Never commit a filled-in `.env`. The key is never logged, returned by an API,
or sent to the browser. Uploaded files are written to
`<MC6_DATA_DIR>/uploads/<job_id>/` and removed when the job reaches a terminal
state.

## Correction workflow

```
Browser selects files and context
  → POST /api/corrections (multipart)
  → job service saves a per-job workspace and validates file bytes
  → queued row in SQLite
  → bounded worker marks the job processing
  → Phase 3 engine (extraction → prompt → provider → JSON validation → checks)
  → storage validates report invariants and persists items + totals atomically
  → job completed
  → GET job/report reads SQLite (no provider call)
  → browser renders the persisted result
```

Lifecycle states: **`queued` → `processing` → `completed` | `failed`**.
A job is completed only after every question row and the report totals have
been committed in one transaction. A provider, extraction, validation or
storage failure marks the job failed with a safe message; it never creates an
empty successful result. Jobs left active by a process restart are reconciled
to `failed` on the next startup, and their workspaces are cleaned. Completed
results remain readable because they live in SQLite, not in the engine's
process-local registry.

Idempotency is supported through the `Idempotency-Key` header
(8–128 characters, letters/digits/`.`/`_`/`:`/`-`). Retrying the same request
returns the existing job instead of creating a duplicate.

### API

| Endpoint | Purpose | Success | Notable failures |
|---|---|---|---|
| `GET /api/health` | liveness probe | `200 {"status":"ok"}` | — |
| `GET /api/system/status` | version, database/engine readiness, feature flags | `200` | — |
| `GET /api/settings` | current server settings | `200` | `503 database_unavailable` |
| `PATCH /api/settings` | update `max_upload_mb` / `default_feedback_detail` | `200` | `422 invalid_request` |
| `GET /api/database/stats` | database counts | `200` | `503 database_unavailable` |
| `GET /api/storage/summary` | bounded storage measurement | `200` | — |
| `POST /api/corrections` | multipart submit | `202` + job | `422 unsupported_input`, `503 engine_unavailable` |
| `GET /api/corrections?limit=50` | recent jobs | `200 {"jobs":[...]}` | — |
| `GET /api/corrections/{job_id}` | durable job state | `200` + job | `404 job_not_found` |
| `GET /api/corrections/{job_id}/report` | persisted report | `200` + report | `404`, `409 report_not_ready` |
| `GET /api/classroom/status` | Classroom connection snapshot | `200` | — |
| `POST /api/classroom/connect` | interactive OAuth connect flow | `200` | `400 classroom_connect_failed` |
| `POST /api/classroom/disconnect` | clear stored credentials | `200` | — |
| `GET /api/classroom/courses` | teacher's active courses (cached) | `200 {"courses":[...]}` | `401 auth_required`, `502 classroom_api_error` |
| `GET /api/classroom/courses/{course_id}/coursework` | coursework list (cached) | `200` | `401`, `502` |
| `GET /api/classroom/…/submissions` | student submissions (cached) | `200` | `401`, `502` |
| `GET /api/classroom/coursework/{id}/ops` | publish-operation audit trail | `200 {"ops":[...]}` | — |

`POST /api/corrections` fields:

- `files` (one or more student submissions) — required
- `mark_scheme_files` (zero or more scheme files)
- `assignment_title` — required
- `instructions`, `mark_scheme` (pasted scheme text)
- `feedback_detail` — `brief` or `detailed`
- `max_score` — optional positive number; a mismatch is flagged for review,
  not used to invent marks
- `Idempotency-Key` header — optional

Accepted bytes: PDF, PNG and JPEG. The server checks the actual file signature,
not just the browser's content type. The effective cap is the smaller of the
engine's 25 MB limit and the server's `max_upload_mb` setting (1–25 MB).
Corrupt, encrypted, empty, mislabelled or oversized files are rejected before
a job row exists.

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

A **completed** job may carry a **partial** report: the run finished, but one
or more questions could not be resolved or verified. Partial reports have no
percentage and are labelled for review. A **failed** job has an error and no
report.

`features.ai_correction` and `features.grade_submission` are true only when a
configured engine, a ready database and a job service are all present.
`features.reports` remains **false** because downloadable report files are not
implemented yet.

If the database cannot initialize, the app starts degraded: the UI and
`/api/health` still work, `/api/system/status` reports
`database.status: "unavailable"`, and data endpoints return a `503`
`database_unavailable` envelope.

## Database and settings

- Schema version 3. `backend/app/migrations/001_initial.sql` contains the
  Phase 2 tables; `002_correction_jobs.sql` adds the correction-job tables;
  `003_classroom.sql` adds the Classroom sync/publish cache tables.
- Tables: `students`, `assignments`, `submissions`, `correction_results`,
  `settings`, `correction_jobs`, `correction_job_files`, `correction_items`.
- Migrations are applied through `PRAGMA user_version` by
  `backend/app/db.py`. A newer database is reported as unavailable rather than
  modified.
- Missing, draft, submitted, graded and failed work are distinct states; a
  zero mark is stored as a real `0`, not as “no result”.
- Question rows preserve labels, marks, maxima, status, feedback, evidence,
  criteria, verification, warnings and review flags.
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

The automated suite never contacts an external AI provider. Provider behavior
is tested against a local HTTP stub, and engine orchestration uses a
deterministic fake model client. `test_api_corrections.py` runs the **real**
Phase 3 engine and the real job service through the HTTP API, with only the
remote provider replaced by a local stub. That verifies the integration,
persistence and failure paths — **not** the live model's marking accuracy.

A separate one-off live run against Gemini (default `gemini-3.5-flash-lite`
configuration, bundled fixture PDFs) completed with 9/10 and persisted the same
per-question report. The automated suite remains provider-free; accuracy across
a wider range of real submissions has not been evaluated.

Phase 4 coverage includes:

- job creation, `queued → processing → completed`, failure, idempotency,
  restart reconciliation and temporary-file cleanup;
- report persistence and total/maximum/percentage consistency checks;
- real multipart uploads, corrupt files, unsupported types, size limits and
  missing mark schemes;
- provider failure, missing engine configuration, not-ready and not-found jobs;
- browser API calls, correction-page states and result rendering;
- a reload and an application restart reading the same completed result from
  SQLite.

## Project structure

```
MATH_CHECKER_V6/
├── main.py                      # launcher: config → uvicorn
├── requirements.txt             # fastapi, uvicorn, python-multipart, pypdf
├── requirements-dev.txt         # + pytest, httpx
├── .env.example                 # configuration template (placeholders only)
├── backend/
│   ├── app/
│   │   ├── config.py            # MC6_* env vars, paths, AI config
│   │   ├── logging_setup.py     # application logger + request-id context
│   │   ├── db.py                # connections, PRAGMAs, migration runner
│   │   ├── migrations/          # 001 initial, 002 jobs, 003 classroom
│   │   ├── models.py            # dataclasses, enums, settings definitions
│   │   ├── storage.py           # the only SQL boundary
│   │   ├── services.py          # settings and statistics services
│   │   ├── engine.py            # engine contract + get_engine()
│   │   ├── correction/          # documents, scheme, prompts, provider,
│   │   │                        # parsing, validation, verify, service, jobs
│   │   ├── classroom/           # OAuth, client, sync, publish ops
│   │   ├── main.py              # FastAPI app, lifecycle, static serving
│   │   └── api/                 # system, settings, database, storage,
│   │                            # corrections, classroom routers
│   └── tests/                   # pytest suite + PDF factory + provider stub
├── frontend/                    # zero-build vanilla SPA
├── scripts/
│   └── e2e_walkthrough.py       # reproducible end-to-end verification
├── PHASE5_AUDIT.md / PHASE5_TEST_REPORT.md /
│   PHASE5_RELIABILITY_REPORT.md
├── CLASSROOM_MIGRATION.md / CLASSROOM_CONFIGURATION.md /
│   CLASSROOM_TEST_REPORT.md
└── docs/
    ├── architecture.md
    ├── correction-engine-contract.md
    ├── phase-1..4-reports.md
    └── screenshots/
```

## What works today

- Complete application shell and five pages, all directly navigable.
- Dashboard: real database counts, submission-status breakdown, recent durable
  jobs, and readiness that reads the live backend state.
- AI Correction: student-work and mark-scheme selection, browser checks
  against the server's upload limit, assignment context, options, real
  multipart submission, job identifier, honest queued/processing states,
  polling, retry on transient status failures, and question-level results.
- Results: persisted marks, maxima, percentage (complete reports only),
  review flags, evidence, warnings and unresolved-question lists. The browser
  never recalculates marks.
- Refresh and restart: a completed job and its report remain available; a
  `?job=` link opens the stored result directly.
- Failure paths: rejected files, engine unavailable, provider failure, storage
  failure and missing jobs all produce explicit states, not fabricated results.
- Settings: real server settings, browser preferences, live diagnostics.
- Storage: real, on-request measurement of the application data directory.
- Task Manager: correction-job guidance plus planned categories with honest
  empty states.

## Not in this release

- Downloadable/generated report files and Edexcel grade boundaries
  (`features.reports` stays false).
- Google Classroom grade/attachment write-back **over HTTP** — the service,
  OAuth flow, cache and safety rules exist and are tested at the service
  layer; the browser-facing routes are future work.
- Authentication and multi-tenant deployment.
- A distributed worker queue or multi-process scheduler. Jobs run in a
  bounded in-process daemon worker; the application is intended as a
  single-process deployment. A restart reconciles active jobs to `failed`
  rather than resuming them.

## Troubleshooting

**Correction is unavailable**
Set `MC6_AI_API_KEY` (and optionally `MC6_AI_MODEL`) in the server environment
or `.env`, then restart. The UI shows the engine's reason rather than failing
silently.

**`MC6_AI_TIMEOUT_SECONDS must be an integer` / similar**
An optional provider setting has an invalid value. Fix or remove it; the error
never prints the key.

**Correction failed**
Open the job on the AI Correction page; the safe error is shown there. Common
causes are an invalid provider key, rate limiting, a timeout, or a PDF whose
content could not be read. The uploaded workspace is removed after failure.

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
`app.db` inside it. Upload workspaces are under `uploads/` and are temporary.

## License

See the repository's license file.
