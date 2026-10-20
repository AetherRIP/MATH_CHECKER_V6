# Math Checker V6 — Phase 4 Completion Report

**Scope:** application integration & end-to-end correction workflow
**Status:** complete for upload → durable job → real Phase 3 engine → persisted
result → browser display. **Version:** 6.3.0 (Phase 4).

Phase 4 did not replace the Phase 1–3 architecture. It connected the existing
pieces through a documented job service, added the durable persistence Phase 3
deliberately left out, and replaced the correction page's placeholders with
real API calls.

---

## 1. Integration architecture

```
Browser (frontend/js/pages/correction.js)
  │  multipart FormData + Idempotency-Key
  ▼
POST /api/corrections                      (thin router)
  │
  ▼
CorrectionJobService                       (backend/app/correction/jobs.py)
  ├─ validates fields, file types/counts/sizes
  ├─ writes <data>/uploads/<job_id>/
  ├─ calls the Phase 3 document extractor to reject bad bytes
  ├─ inserts a queued job row
  └─ starts a bounded daemon worker
        │
        ▼
  queued → processing
        │
        ▼
  Phase 3 CorrectionEngine (real implementation)
  documents → scheme blueprint → provider → JSON parse → validation → verify
        │
        ▼
  Storage.complete_correction_job()
  validates the report again, inserts every question row and report totals in
  one transaction, then sets status = completed
        │
        ▼
  workspace removed in a finally block
        │
        ▼
GET /api/corrections/{id} and /report      (SQLite only; no provider call)
        │
        ▼
Browser renders persisted marks, maxima, evidence and warnings
```

The frontend contains no marking rules, PDF extraction, provider calls or
secret material. `api.js` is the only network seam; pages never call `fetch()`
directly.

### Lifecycle

| State | Meaning |
|---|---|
| `queued` | Durable row exists and the upload workspace is complete. Waiting for a worker slot. |
| `processing` | A worker claimed the job and the engine is running. |
| `completed` | Every question row and report total were committed. The report is retrievable. |
| `failed` | Validation, extraction, provider, engine-output or storage failure. A safe error is stored; no report exists. |

Rules enforced in code:

- A job is completed **after** its report is persisted, in the same transaction.
- A completed job cannot be reopened by a failure or a second completion.
- A failed job cannot be overwritten by a later success.
- Jobs left `queued`/`processing` by a process restart are reconciled to
  `failed` with an “interrupted by a restart” message; their workspaces are
  pruned. Completed/failed jobs survive unchanged.
- Idempotency keys use a partial UNIQUE index. A retried request returns the
  existing job rather than creating a duplicate.
- Concurrency is bounded to two in-process workers; the Phase 3 engine also
  bounds provider calls to two. This is a single-process design, not a
  distributed queue.

## 2. Files created, modified or removed

### Created

| File | Reason |
|---|---|
| `backend/app/migrations/002_correction_jobs.sql` | Schema version 2: durable jobs, input metadata and per-question rows; lifecycle/status checks; idempotency index. |
| `backend/app/correction/jobs.py` | Job service: validation, workspace ownership, bounded worker, transitions, cleanup, restart reconciliation. |
| `backend/app/api/corrections.py` | Thin multipart/upload/list/status/report routes and wire serialisation (no paths or scheme text). |
| `backend/tests/test_correction_jobs.py` | Unit tests for validation, lifecycle, idempotency, cleanup, recovery and storage consistency. |
| `backend/tests/test_api_corrections.py` | API/integration tests using the real job service + real Phase 3 engine over a local provider stub. |
| `docs/phase-4-report.md` | This report. |

No application files were removed. The Phase 1–3 modules remain the owners of
their respective concerns.

### Modified

| File | Change |
|---|---|
| `backend/app/config.py` | Version 6.3.0 / Phase 4; `uploads_dir` under `MC6_DATA_DIR`; create it at startup. |
| `backend/app/db.py` | Current schema version 2 and required job/result tables. |
| `backend/app/models.py` | `CorrectionJobFile` / `CorrectionJobRecord`; imports the engine's `JobStatus` vocabulary. |
| `backend/app/storage.py` | Job create/read/list/claim/complete/fail/recover/report methods; report invariant validation at the persistence boundary. |
| `backend/app/engine.py` | `CorrectionRequest.job_id` for durable/engine correlation; safer unavailable-engine wording. |
| `backend/app/correction/service.py` | Invalid provider configuration is reported without exposing environment variable names or secret values. |
| `backend/app/main.py` | Construct the engine once, construct the job service after storage, run restart reconciliation, register the router. |
| `backend/app/api/deps.py` | `get_job_service` dependency with the degraded-database 503 behaviour. |
| `backend/app/api/system.py` | Readiness now requires engine + job service + ready database; correction job/background flags reflect that. |
| `backend/app/api/storage.py` | Added a bounded “Job uploads” category so temporary workspaces are visible without misleading totals. |
| `backend/app/api/__init__.py` | Router inventory updated. |
| `backend/tests/test_api_database.py`, `test_api_system.py`, `test_services.py`, `test_storage.py` | Schema/version/feature-flag expectations updated for Phase 4. |
| `backend/tests/test_api_degraded.py` | A broken database now also disables correction/job readiness flags. |
| `backend/tests/test_engine.py` | Unavailable messages no longer expose environment variable names. |
| `frontend/js/api.js` | `corrections.submit/list/get/report` with multipart, idempotency header and long upload timeout. |
| `frontend/js/pages/correction.js` | Real uploads, server upload limit, validation, job submission, polling, retry, persisted job/report rendering, `?job=` deep links, refresh/restart retrieval. |
| `frontend/js/pages/dashboard.js` | Recent durable jobs table, real job states and readiness. |
| `frontend/js/pages/storage.js` | Empty-state wording now explains temporary correction uploads. |
| `frontend/js/pages/tasks.js` | Correction-job guidance instead of claiming no task system exists. |
| `frontend/js/ui/tabs.js` | Exported programmatic tab selection (used to open results after start/refresh). |
| `frontend/css/components.css` | Job-detail, spacing and disclosure styles consistent with existing tokens. |
| `frontend/package.json` | Version 6.3.0. |
| `frontend/tests/api.test.mjs`, `frontend/tests/pages.test.mjs` | Correction endpoint, correction-page validation/state and job markup tests. |
| `README.md`, `docs/architecture.md`, `docs/correction-engine-contract.md` | Phase 4 setup, API, lifecycle, persistence and file map. |
| `docs/phase-1-report.md`, `docs/phase-2-report.md`, `docs/phase-3-report.md` | Roadmap notes updated so historical reports do not claim Phase 4 is still pending. |
| `.env.example`, `requirements.txt` | Upload directory/provider-restart notes; Phase 4 runtime dependency description. |
| `main.py` | Launcher help text and phase wording. |

## 3. API endpoints and lifecycle

| Endpoint | Purpose | Behaviour |
|---|---|---|
| `POST /api/corrections` | Multipart submission | Validates inputs; writes workspace; returns `202` with the queued job. `422` for invalid input, `503` if engine/database unavailable. |
| `GET /api/corrections?limit=50` | Recent jobs | Newest first; metadata only (no server paths, no scheme text). |
| `GET /api/corrections/{job_id}` | Current durable state | `404 job_not_found` when absent. |
| `GET /api/corrections/{job_id}/report` | Persisted report | `409 report_not_ready` for queued/processing/failed jobs; no provider call. |

`POST` fields: `files`, optional `mark_scheme_files`, `assignment_title`,
`instructions`, `mark_scheme` (pasted text), `feedback_detail`, optional
`max_score`, and optional `Idempotency-Key` header.

A **completed job** can hold a **partial report**: the run finished, but some
questions were unresolved/unreadable/ambiguous. Partial reports carry no
percentage and are labelled for review. A failed job never has a report.

Accepted uploads: PDF, PNG, JPEG. The server checks magic bytes, page structure
and encryption; it uses the configured 1–25 MB cap and the engine's 25 MB
ceiling. Invalid input is rejected before a job row or provider call exists.

## 4. Data flow from upload to saved result

1. User selects student work and mark scheme on the AI Correction page.
2. Browser checks extension and size against `/api/settings`; server revalidates
   the bytes.
3. `FormData` is posted with a generated idempotency key.
4. `CorrectionJobService` creates a job workspace and copies uploads under
   generated names.
5. Each file is extracted once at the boundary to reject corrupt/encrypted/
   mislabelled content. (The engine extracts again for its own prompt, so a
   valid PDF is parsed twice; no file is uploaded twice.)
6. A `queued` row and input metadata are committed.
7. The worker claims the job (`processing`) and calls the Phase 3 engine with
   the Phase 4 job id.
8. The engine returns a typed `CorrectionReport` (or a failed `CorrectionJob`).
9. `Storage.complete_correction_job()` validates labels, marks, maxima,
   unresolved lists, totals and percentage, inserts all question rows, and
   sets `completed` in one SQLite transaction.
10. The workspace is deleted on every terminal path.
11. The browser polls the job, fetches the stored report once complete, and
    renders question-level marks/evidence. It never recalculates marks.
12. A refresh or application restart reads the same rows from SQLite.

## 5. Tests executed and outcomes

**Backend:** `PYTHONPATH=backend .venv/Scripts/python -m pytest backend/tests -q`
→ **185 passed** (1 Starlette/httpx deprecation warning). No failures.

**Frontend:** `cd frontend && npm test`
→ **48 passed**, 0 failed, 0 skipped.

Phase 4 coverage added:

- Unit: input validation, job creation, state transitions, engine invocation,
  report persistence, failure handling, total consistency, workspace cleanup,
  idempotency, restart reconciliation, unavailable engine.
- Integration: API → job service → real engine → storage → API report, using a
  local HTTP provider stub. Includes persisted totals, per-question marks,
  provider failure, invalid input, not-ready/not-found, upload limit and
  idempotent retries.
- Frontend: corrections API calls (multipart, idempotency header, list/status/
  report, error envelope), correction-page draft validation and stable markup.
- Regression: the full Phase 1–3 backend and frontend suites still pass.

**Mocked vs real provider:** all automated tests replace only the remote
provider call. The real engine, extraction, validation, storage and HTTP
layers run. No paid provider quota was consumed.

### Browser verification performed

With a local provider stub and a temporary data directory:

1. Opened `/#/correction`, confirmed “Engine ready” and the server-provided
   25 MB limit.
2. Selected the bundled V5 student PDF and mark-scheme PDF; the review panel
   showed filenames, sizes and types.
3. Entered an assignment title and submitted. The job identifier appeared and
   the UI moved through `Completed` without fabricated percentage progress.
4. Opened Results: **9 / 10, 90%**, four question rows (`3/3`, `2/2`, `2/3`,
   `2/2`) and evidence disclosures.
5. Reloaded the browser; the `?job=` link reopened Results with the same saved
   marks.
6. Stopped and restarted the application against the same data directory; the
   completed job and report were still readable, with no provider call.
7. Confirmed the uploaded workspace was removed after completion.

The automated API suite additionally verified provider failure and invalid
uploads through the HTTP interface.

### Live provider verification performed

Against the real Gemini endpoint (no stub), with a temporary data directory and
the default model configuration:

1. `GET /api/system/status` reported `gemini:gemini-3.5-flash-lite` available.
2. Uploaded the bundled student and mark-scheme PDFs. The job moved
   `queued → processing → completed` in about 30 seconds.
3. `GET /api/corrections/{id}/report` returned **9 / 10 (90%)**, four marked
   questions, no warnings and an empty unresolved list.
4. Opened `/#/correction?job=…` in the browser: Results showed the persisted
   summary and per-question feedback, with no console errors and all asset and
   API requests returning 200.
5. Confirmed the completed row and report rows in SQLite.

During this session `gemini-3.5-flash` repeatedly returned HTTP 503 (provider
capacity) for the full marking prompt, so `gemini-3.5-flash-lite` is the
default; `MC6_AI_MODEL` can select another model when capacity allows. The
retired `gemini-2.5-flash` default was replaced after a live 404 from the
provider.

## 6. Known limitations and unresolved defects

- **No generated report files.** `features.reports` remains false. The report
  *view* is implemented; a downloadable PDF/CSV report is deferred. Any future
  generator must consume persisted `CorrectionItem` rows, not re-run marking.
- **Single-process assumption.** Daemon workers and startup reconciliation are
  designed for one application process. Running multiple uvicorn workers would
  need an external queue/lease and is explicit non-goal work.
- **Restarts fail active jobs.** A job that was queued/processing during a
  crash is marked failed rather than resumed; the user must resubmit. This is
  honest and safe, but not resumable.
- **No broad live-model accuracy claim.** One live Gemini run on the bundled
  fixtures completed correctly; automated verification still uses a
  deterministic local provider. Marking accuracy and consistency across a wide
  range of real submissions have not been evaluated.
- **Double PDF extraction.** Upload validation and the engine both extract a
  valid PDF. This keeps the Phase 3 contract intact; a future optimization
  could pass the extracted document through the interface.
- **No report-file download, Classroom sync, authentication, class/roster
  management, grades or multi-account support.** These remain out of scope.
- **No percentage progress.** The engine cannot report reliable progress;
  the UI shows queued/processing only.
- **Large uploads are spooled by the ASGI server before the application reads
  them.** The configured size limit is enforced while copying into the job
  workspace; an upstream proxy limit is still advisable for deployment.

## 7. Running locally

```bash
cd MATH_CHECKER_V6
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # Windows
# .venv/bin/python -m pip install -r requirements-dev.txt     # macOS/Linux
```

Set a server-side provider key (never in the browser), for example:

```bash
export MC6_AI_API_KEY="..."
# optional: MC6_AI_MODEL, MC6_AI_BASE_URL, MC6_AI_TIMEOUT_SECONDS, MC6_AI_MAX_RETRIES
```

Or copy `.env.example` to `.env` and fill only the key. Restart after changing
provider configuration.

```bash
.venv/Scripts/python main.py
# open http://127.0.0.1:8643/#/correction
```

Runtime data (SQLite database and temporary upload workspaces) lives under
`MC6_DATA_DIR` (default `./data`).

## 8. Running the tests

```bash
PYTHONPATH=backend .venv/Scripts/python -m pytest backend/tests -q
cd frontend && npm test
```

The backend suite uses a local provider stub; no external network or API key is
required for tests.

## 9. Configuration required

| Variable | Required for | Notes |
|---|---|---|
| `MC6_AI_API_KEY` | Running a correction | Server-side only; absent = engine unavailable, UI disables Start. Read at startup. |
| `MC6_AI_MODEL` | Optional | Default `gemini-3.5-flash-lite`. |
| `MC6_AI_BASE_URL` | Optional | Default Gemini endpoint; useful for a local stub in verification. |
| `MC6_AI_TIMEOUT_SECONDS` | Optional | 5–600, default 180. |
| `MC6_AI_MAX_RETRIES` | Optional | 0–5, default 2. |
| `MC6_DATA_DIR` | Optional | Database + upload workspaces. |
| `MC6_HOST`, `MC6_PORT`, `MC6_LOG_LEVEL`, `MC6_DEBUG` | Optional | Standard runtime settings. |

No key or secret is written to the database, logs, browser storage or API
responses.

## 10. Verified end-to-end scenarios

| Scenario | Method | Result |
|---|---|---|
| Valid student PDF + mark scheme → job → real engine → persisted report | API integration test (local stub) and browser run | Passed; 9/10, four items, totals consistent |
| Unreadable question → completed job with partial report | API integration test | Passed; no percentage, unresolved question preserved |
| Job lifecycle and processing claim | Unit test with controlled worker | Passed |
| Refresh shows completed result | Browser reload with `?job=` | Passed |
| Application restart keeps completed result | Stopped/restarted server, same data dir | Passed |
| Provider failure | API test with 500 stub | Job failed, safe error, no report |
| Invalid/corrupt/unsupported upload | API tests | `422`, no job row, no provider call |
| Missing engine configuration | API test | `503 engine_unavailable`, no job |
| Duplicate retry with same idempotency key | API/unit tests | One job, one provider call |
| Upload limit from settings | API test | Rejected, workspace cleaned |
| Interrupted job recovery | Unit test | Failed with restart message, workspace cleaned |
| Report total mismatch is rejected | Storage unit test | `StorageError`, job stays processing |
| Degraded database readiness | Backend tests | Data routes 503; correction flags false |

## 11. Roadmap

| Phase | Status |
|---|---|
| 1 — Interface foundation | Complete |
| 2 — Backend foundation | Complete |
| 3 — Mathematical correction engine | Complete (live-accuracy evaluation deferred) |
| 4 — Application integration | Complete for upload → durable job → engine → persisted result → UI. Report-file generation deferred. |
| Later — Report files, Classroom sync, rosters, deployment hardening | Deferred |
