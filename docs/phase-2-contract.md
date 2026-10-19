# Phase 2 contract — the correction engine

**Status: contract only. No engine code exists.** This document and
`backend/app/engine.py` were written *before* any engine implementation so
that Phase 2 has a fixed seam to build against. The engine module is the
**executable half** of the contract (data types, the `CorrectionEngine`
protocol, the input policy); this document is the **behavioral half** (HTTP
surface, job lifecycle, error semantics, frontend wiring).

Phase 1 ships `UnavailableEngine`, a stub that reports honestly that
correction cannot run yet and raises `EngineUnavailableError` instead of
inventing results. Nothing in Phase 1 claims to grade anything.

---

## 1. Engine surface (`backend/app/engine.py`)

| Method | Kind | Contract |
|---|---|---|
| `describe() -> EngineInfo` | sync, cheap | What the engine is and whether it can run. Drives readiness UI. Never raises for "not configured" — that is data (`available: false`, `reason`). |
| `submit(request) -> CorrectionJob` | async | Validates via `validate_request`, accepts a job, returns it in `queued` state. Raises `UnsupportedInputError` or `EngineUnavailableError`. |
| `get_job(job_id) -> CorrectionJob` | async | Current job state. Raises `JobNotFoundError` for unknown ids. |
| `get_report(job_id) -> CorrectionReport` | async | Grading output for a `completed` job. Raises `JobNotFoundError` for unknown ids and `EngineError` if the job has not completed. |

`get_engine() -> CorrectionEngine` is the only construction point. Callers
(API routers, services) depend on the protocol, never on a concrete class.

## 2. Data model

Dataclasses in `engine.py` are the source of truth. Wire shapes are the same
names in JSON. **Server-side paths never appear on the wire** — only
filenames, media types and sizes.

| Type | Fields | Notes |
|---|---|---|
| `SubmissionFile` | `path` (server-only), `filename`, `media_type`, `size_bytes` | One uploaded file. |
| `AssignmentContext` | `title`, `instructions`, `mark_scheme` | From the correction page's assignment draft. Empty strings allowed. |
| `CorrectionOptions` | `partial_credit: bool`, `max_score: float \| null` | From the options draft. Extensible in Phase 2; fields are added, never repurposed. |
| `CorrectionRequest` | `files`, `assignment`, `options` | One grading batch. |
| `MarkedItem` | `label`, `awarded`, `out_of`, `feedback` | One question's verdict. `awarded`/`out_of` are `null` when not applicable. |
| `CorrectionReport` | `job_id`, `summary`, `awarded`, `out_of`, `items` | The grading output. |
| `CorrectionJob` | `job_id`, `status`, `submitted_at` (ISO 8601 UTC), `files` (filenames only), `error` | `error` is a user-safe message when `status` is `failed`. |
| `EngineInfo` | `name`, `available`, `reason` | `reason` explains unavailability in plain language. |

### Input policy (single owner: `validate_request`)

- Accepted media types: `application/pdf`, `image/png`, `image/jpeg`.
- Maximum size per file: **25 MB** (`MAX_FILE_BYTES`).
- At least one file is required.

These are the exact limits the frontend enforces in
`frontend/js/pages/correction.js`; `test_engine.py` locks the constants so
the three places cannot drift silently. The backend check is authoritative.

## 3. Job lifecycle

```
            submit()
               │
               ▼
            queued ──────────▶ failed   (validation/engine error)
               │                   ▲
               ▼                   │
           processing ─────────────┘   (engine error mid-run)
               │
               ▼
           completed ──▶ report available via get_report()
```

- `queued` → `processing` → `completed` | `failed`. `completed` and `failed`
  are terminal.
- `failed` jobs carry a user-safe `error` message on the job itself.
- A report exists **only** for `completed` jobs. Nothing fabricates one.
- No polling loops and no background workers in this contract. Job state is
  read through status endpoints; optional SSE for live progress is an
  explicitly later extension (architecture §6).

## 4. HTTP API (Phase 2 adds these routes)

New router: `backend/app/api/corrections.py`, registered by `main.py` like
the existing routers. All errors use the existing envelope:

```json
{ "error": { "code": "engine_unavailable", "message": "…", "request_id": "…" } }
```

| Endpoint | Purpose | Success | Notable failures |
|---|---|---|---|
| `POST /api/corrections` | Submit files + assignment + options (multipart: repeated `files`, JSON `assignment`, JSON `options`) | `202` + `CorrectionJob` (wire shape) | `422 unsupported_input`, `503 engine_unavailable` |
| `GET /api/corrections` | Recent jobs (fills the Task Manager categories) | `200` + `{ "jobs": [CorrectionJob] }` | — |
| `GET /api/corrections/{job_id}` | Job state | `200` + `CorrectionJob` | `404 job_not_found` |
| `GET /api/corrections/{job_id}/report` | Grading output | `200` + `CorrectionReport` (wire shape) | `404 job_not_found`, `409 report_not_ready` |

### Error codes → HTTP status

| `code` | HTTP | Raised by |
|---|---|---|
| `unsupported_input` | 422 | `validate_request` |
| `engine_unavailable` | 503 | `EngineUnavailableError` (e.g. no `MC6_AI_API_KEY`) |
| `job_not_found` | 404 | `JobNotFoundError` |
| `report_not_ready` | 409 | report requested before `completed` |
| `internal_error` | 500 | anything else (existing `main.py` handler) |

Routers map `EngineError` subclasses to this table; they never leak stack
traces or paths (existing rule, architecture §3).

## 5. Frontend wiring

The frontend rule stands: **pages never call `fetch()`** — `api.js` is the
only module that talks to the backend.

| Seam | Change in Phase 2 |
|---|---|
| `frontend/js/api.js` | Adds `corrections.submit(formData)`, `corrections.list()`, `corrections.get(id)`, `corrections.report(id)` next to the existing `health` / `storageSummary` / `systemStatus`. |
| `frontend/js/pages/correction.js` | "Start correction" enables **only** when `systemStatus().features.ai_correction` is true; its explanation note then reflects `EngineInfo.reason` when unavailable. The review list, options draft and confirm modal already exist and keep their behavior. |
| `frontend/js/pages/tasks.js` | The four category tabs fill from `GET /api/corrections`; empty states stay until real jobs exist. |
| `frontend/js/pages/dashboard.js` | Jobs/reports counters fill from the same responses; readiness panel reads the feature flags. |
| `frontend/js/pages/storage.js` | The "Reports" category starts reporting real files once reports land in `MC6_DATA_DIR/reports` (already created by `ensure_dirs`). |

Honesty rules for the UI are unchanged: empty, loading, error and disabled
states are real; nothing is displayed as working before it is.

## 6. Rules for implementers (Phase 2 checklist)

1. Implement `CorrectionEngine`; register it in `get_engine()` — that is the
   only construction point. Keep `UnavailableEngine` as the fallback.
2. Call `validate_request` first. Do not re-implement limit checks anywhere.
3. Flip the feature flags in `backend/app/api/system.py` (`ai_correction`,
   `pdf_processing`, `grade_submission`, `reports`) **only** when the
   capability genuinely works end to end. They drive the Dashboard
   readiness panel.
4. Secrets (`MC6_AI_API_KEY`, OAuth material) stay server-side. No response,
   log or report contains them, or server filesystem paths.
5. Tests at both layers for every new capability (pytest for the engine and
   routes; node --test for render states), and a doc update when this
   contract changes.
6. Never return fabricated or placeholder results. An engine that cannot
   grade says so via `EngineInfo.reason` and `EngineUnavailableError`.

## 7. Non-goals of this contract

Google Classroom sync (its own `classroom.py` seam), authentication,
databases, background workers / job queues, PDF extraction internals,
provider choice and key rotation policy, report file formats. Each gets its
own contract when its phase starts.
