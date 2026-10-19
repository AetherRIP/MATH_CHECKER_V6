# Math Checker V6 — Phase 2 Completion Report

**Scope:** backend foundation & live UI wiring · **Status:** complete ·
**Version:** 6.1.0 (Phase 2)

Phase 2 turned the Phase 1 interface into a working foundation: a local
SQLite database behind one storage boundary, typed settings, honest health
and status endpoints, consistent error handling, deterministic fixtures, and
a UI that reads live backend data. The AI correction engine is **not** part
of this phase; it moves to Phase 3.

---

## 1. Files created and modified

**Backend — created**

| File | Purpose |
|---|---|
| `backend/app/db.py` | SQLite connection lifecycle, PRAGMAs, `PRAGMA user_version` migration runner, safe database status |
| `backend/app/migrations/001_initial.sql` | schema version 1 |
| `backend/app/models.py` | dataclasses, enums, IDs/timestamps, typed settings definitions and validation |
| `backend/app/storage.py` | the only SQL boundary: records, settings, statistics |
| `backend/app/services.py` | `SettingsService` and `StatsService` |
| `backend/app/dev_fixtures.py` | deterministic, idempotent development seed |
| `backend/app/logging_setup.py` | application logger and request-id context |
| `backend/app/api/deps.py` | storage/settings/stats dependency providers |
| `backend/app/api/errors.py` | `ApiError` and the shared error envelope |
| `backend/app/api/error_handlers.py` | validation, settings, SQLite and unexpected-error handlers |
| `backend/app/api/settings.py` | `GET` / `PATCH /api/settings` |
| `backend/app/api/database.py` | `GET /api/database/stats` |

**Backend — modified**

| File | Change |
|---|---|
| `backend/app/config.py` | `database_path` under the data directory; version `6.1.0`, phase `2` |
| `backend/app/main.py` | lifespan initializes the database and logging; request-id middleware; Phase 2 routers; degraded-start handling |
| `backend/app/api/system.py` | status reports `database.status`, `schema_version` and safe detail |
| `backend/app/api/__init__.py` | Phase 2 route description |
| `backend/app/engine.py` | contract wording retargeted to Phase 3 (behaviour unchanged) |
| `main.py` | `--seed-dev`, Phase 2 banner, `access_log=False` |

**Frontend — modified / created**

| File | Change |
|---|---|
| `frontend/js/api.js` | JSON request bodies, backend error messages, `settings` and `databaseStats` |
| `frontend/js/pages/dashboard.js` | live DB counts, submission-status table, database readiness row, loading/empty/error states |
| `frontend/js/pages/settings.js` | real server settings with loading/error/save states; live diagnostics; local preferences unchanged |
| `frontend/js/pages/correction.js` | reads server upload limit and feedback default; later-phase wording |
| `frontend/js/layout/shell.js` | version/phase label comes from the status response |
| `frontend/js/main.js` | sets the real version label from status |
| `frontend/js/pages/tasks.js`, `frontend/js/pages/storage.js` | stale phase wording |
| `frontend/package.json` | version `6.1.0` |
| `frontend/tests/api.test.mjs` | new request/error-state tests |
| `frontend/tests/pages.test.mjs` | updated live-placeholder and phase-wording tests |

**Docs — modified / created**

| File | Change |
|---|---|
| `docs/phase-2-contract.md` | renamed to `docs/correction-engine-contract.md`; retargeted to Phase 3 |
| `docs/architecture.md` | rewritten for the Phase 2 storage/API architecture |
| `docs/phase-1-report.md` | roadmap note and stale phase references corrected |
| `docs/phase-2-report.md` | this report |
| `README.md` | Phase 2 setup, API, database and testing documentation |
| `.env.example` | documents the SQLite database under the data directory |

## 2. Architecture and major design decisions

- **Keep the serving layer, add one storage boundary.** FastAPI + uvicorn
  remain; SQLite comes from the standard library. There is no ORM, no
  migration package, no worker and no external service.
- **One SQL owner.** `backend/app/storage.py` is the only module that runs
  SQL. Routes and services depend on named methods, never on a connection.
- **One schema owner.** Numbered SQL files in `backend/app/migrations/` are
  applied by `PRAGMA user_version`. A newer database is reported rather than
  modified.
- **Migration/validation ownership.** Data rules live in `models.py` and
  `storage.py`; HTTP request rules live in `api/settings.py` and the shared
  error handlers. The 25 MB upload cap is shared with the engine contract.
- **Degraded startup instead of a crash.** A data-directory or database
  failure leaves the UI and `/api/health` available, reports
  `database.status: "unavailable"`, and answers data routes with a `503`
  `database_unavailable` envelope.
- **No fabricated UI values.** Dashboard counts and readiness come from the
  API; the shell version comes from status; settings are read and written
  through the API. Browser-only preferences stay in `localStorage`.
- **No heavyweight infrastructure.** Single process, no background workers,
  no polling, no Redis/Docker requirement, no startup network calls.

## 3. Database schema and initialization approach

Schema version 1 (`backend/app/migrations/001_initial.sql`):

| Table | Key columns | Rules |
|---|---|---|
| `settings` | `key` PK, `value`, `updated_at` | typed values validated in `models.py` |
| `students` | `id` PK, `display_name`, `email`, `external_id`, timestamps | unique `external_id` when present |
| `assignments` | `id` PK, `title`, `qualification`, `component`, `lesson_code`, `notes`, `max_score`, timestamps | `lesson_code` stored verbatim; duplicates allowed because identity is the record id |
| `submissions` | `id` PK, `assignment_id`, `student_id`, `status`, file metadata, `submitted_at`, timestamps | one per `(assignment_id, student_id)`; missing/draft require no submitted time; submitted/graded/failed require one |
| `correction_results` | `id` PK, `submission_id` UNIQUE, `outcome`, `awarded`, `out_of`, `summary`, `feedback`, `error`, timestamps | completed results require `0 <= awarded <= out_of`; failed results forbid marks; **zero is a real value** |

Initialization: each connection enables WAL, foreign keys, a 5-second busy
timeout and `synchronous=NORMAL`. `Database.initialize()` reads
`PRAGMA user_version`, applies pending numbered scripts idempotently, then
records the new version. `Database.status()` reports ready/unavailable with
the schema version and a safe detail message.

## 4. Implemented API routes and service interfaces

| Interface | Behaviour |
|---|---|
| `GET /api/health` | liveness only: `{"status": "ok"}` |
| `GET /api/system/status` | version, phase, database readiness and honest feature flags |
| `GET /api/settings` | `{"settings": {"max_upload_mb": 25, "default_feedback_detail": "detailed"}, "limits": {"max_upload_mb": {"minimum": 1, "maximum": 25}}}` |
| `PATCH /api/settings` | partial update; 422 for empty/unknown/out-of-range/wrong-type values; 503 when the database is unavailable |
| `GET /api/database/stats` | database status plus student, assignment, submission-by-state and correction counts |
| `GET /api/storage/summary` | unchanged real filesystem measurement (now includes `app.db`) |

Storage interface: `get_settings`, `update_settings`, `create_student`,
`get_student`, `list_students`, `update_student`, `create_assignment`,
`get_assignment`, `list_assignments`, `update_assignment`,
`create_submission`, `get_submission`, `get_submission_for`,
`list_submissions`, `update_submission_status`, `record_correction`,
`get_correction_for_submission`, `database_status`, `stats`.

Services: `SettingsService.get/update` and `StatsService.snapshot`.

## 5. Dependencies added and why

**None.** The database uses the standard-library `sqlite3` module. The
frontend still has zero npm dependencies; its tests use Node's built-in test
runner. This keeps the runtime at two direct packages (`fastapi`, `uvicorn`)
and the deployment free of paid services or credentials.

## 6. Tests executed and actual results

| Command | Result |
|---|---|
| `PYTHONPATH=backend .venv/Scripts/python -m pytest backend/tests -q` | **72 passed**, exit 0 (1 pre-existing Starlette/httpx deprecation warning) |
| `cd frontend && npm test` | **42 passed, 0 failed**, exit 0 |

Backend coverage includes fresh initialization and idempotence, schema-version
safety, CRUD, zero marks, missing/draft/submitted/graded separation, exact
lesson codes, one-result-per-submission, cascade deletes, settings
validation, settings/statistics API behaviour, consistent validation and
database-failure envelopes, degraded startup, and log-value safety.

Frontend coverage includes request shapes, backend error-message extraction,
network/timeout errors, live dashboard placeholders, database readiness
rows, submission-status rendering, server-settings markup, and phase wording.

Manual verification:

- Real server run on `:8666`: health 200, status `ready`/schema 1, settings
  defaults, stats zeros, valid `PATCH` 200, invalid `PATCH` 422 envelope,
  unknown secret field 422 without echoing the value, static UI 200.
- Real degraded run with an unwritable data path: health 200, UI 200,
  status `unavailable`, settings/stats 503 envelopes.
- `python main.py --seed-dev` run twice: second run created zero records.
- Log inspection: settings values and secret-looking input did not appear in
  logs; health/status requests stay at DEBUG.

## 7. Known limitations and unresolved issues

- **No automated browser (E2E) tests.** A browser framework would add a large
  dependency; interactions are covered by pure render tests and manual
  checks. The live-wiring verification was performed against a real server.
- **No per-question correction data yet.** `correction_results` stores the
  summary/feedback for one submission; question-level items arrive with the
  Phase 3 engine.
- **No jobs table.** The Dashboard's recent-jobs table stays empty until
  Phase 3 adds job persistence; it says so honestly.
- **Classes/rosters are deferred.** Students are not yet grouped; grouping
  arrives with the Classroom/roster work.
- **SQLite is single-writer.** Appropriate for one local/server process;
  multi-process deployment needs a different storage plan.
- **`app.db-wal`/`app.db-shm`** may appear in the data directory while the
  database is open; the Storage page counts them as persistent data.

## 8. Exact commands to start and test

```bash
# Install
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # or requirements.txt to run

# Start
.venv/Scripts/python main.py                  # http://127.0.0.1:8643
.venv/Scripts/python main.py --port 8650      # alternate port

# Optional deterministic development data (idempotent)
.venv/Scripts/python main.py --seed-dev

# Backend tests
PYTHONPATH=backend .venv/Scripts/python -m pytest backend/tests -q

# Frontend tests
cd frontend && npm test
```

## 9. Confirmation that the Phase 1 UI remains functional

- Navigation, routing, active state, sidebar collapse, mobile drawer, skip
  link and focus handling are unchanged.
- All five pages and the not-found page render; the existing frontend test
  suite still passes.
- Visual design, tokens, components and layout are unchanged; Phase 2 only
  replaces hardcoded values with live data and adds loading/error states.
- Browser-only preferences still persist in `localStorage`; no server
  credentials or secrets are stored in the browser.

## 10. Recommendation for Phase 3

Implement the correction engine end to end against the existing seam:

1. Add the job/result persistence tables (job lifecycle and per-question
   items) as migration `002`, reusing the storage boundary.
2. Implement `CorrectionEngine` in `backend/app/engine.py`, register it in
   `get_engine()`, and add `backend/app/api/corrections.py` with the HTTP
   surface in `docs/correction-engine-contract.md`.
3. Add the provider client behind `MC6_AI_API_KEY`, with retry/rotation
   policy kept out of the HTTP layer.
4. Wire `frontend/js/pages/correction.js` to upload files and poll job state
   (no fake results; disabled states stay until the engine genuinely works).
5. Flip the `ai_correction`, `pdf_processing`, `grade_submission` and
   `reports` feature flags only when each capability works end to end, and
   update the Dashboard readiness panel accordingly.

Do not start Phase 3 automatically; it is a separate approved phase.
