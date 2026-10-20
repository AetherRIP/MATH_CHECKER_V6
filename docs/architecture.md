# Math Checker V6 — Architecture

**Phase 4 · Application Integration**

This document records the architecture chosen for V6, why it was chosen over
the alternatives, the dependency budget, and exactly where later phases plug
in. Read this before adding features.

---

## 1. Where V6 came from: V5 inspection findings

V5 (`MATH_CHECKER_V5`) was inspected before any V6 code was written:

| Area | V5 reality |
|---|---|
| Entry point | `main.py` launcher → FastAPI app via uvicorn (port 8642) |
| Backend | FastAPI + SQLite + a large module tree (`engine/`, `jobs/`, `workers/`, `gemini/`, `classroom/`, `distributed/`, `large_pdf/`, `repair/`, `reporting/`, 13 API route modules) |
| Frontend | React 18 + TypeScript + Vite, 20+ page components, code-split bundle (~824 KB on disk) |
| Tests | Large pytest suite + Vitest-style frontend tests |
| Runtime deps | 12 direct (fastapi, uvicorn, python-multipart, google-genai, google-auth, google-auth-oauthlib, requests, openpyxl, reportlab, pymupdf, pypdf, Pillow, cryptography) |
| Carried-forward debt | secret-store scanning, multi-account/distributed layer, demo mode, autostart/portable-build machinery, adaptive polling hooks, chart library |

**Decisions taken from that inspection:**

1. Keep the proven serving layer: Python + FastAPI + uvicorn.
2. Do **not** carry V5's frontend toolchain. Its complexity (React, Vite,
   TypeScript, 20+ page components) is disproportionate to the UI V6 needs.
3. Keep V5's correction engine **out of V6 until Phase 3**. It integrates
   through a documented boundary (§6) rather than being copied into page
   components.
4. Use the standard-library `sqlite3` module directly instead of adding an
   ORM or migration framework. The schema is small, migrations are numbered
   SQL files, and there is exactly one storage boundary.
5. V5 was left untouched. Its git tree was clean before work began and
   re-verified clean afterwards.

## 2. Chosen stack

```
Browser ── static files ──▶ FastAPI (uvicorn)
   │                            │
   └── JSON + multipart ──▶ /api/health, /api/system/status, /api/settings,
                            /api/database/stats, /api/storage/summary,
                            /api/corrections
                                │
                                ▼
                        Storage (sole SQL boundary)
                                │
                                ▼
                        SQLite  data/app.db

Correction pipeline (Phases 3–4):
validate request → upload workspace → validate/extract documents →
scheme blueprint → provider → JSON + mark validation → deterministic checks
→ validate report → persist items + totals → completed job
```

- **Backend:** FastAPI + uvicorn + python-multipart + pypdf. Four runtime
  dependencies. The database is the standard-library `sqlite3`; no ORM, no
  migration package, no external service, no startup network call. Jobs run
  in a bounded in-process daemon worker, not a distributed queue.
- **Storage:** SQLite in the configured data directory (`MC6_DATA_DIR`, or
  `./data`). WAL mode, foreign keys and a busy timeout are set on every
  connection; each operation opens and closes its own connection.
- **Frontend:** vanilla HTML/CSS/ES modules served as static files.
  **No build step.** Pages are fetched on demand via dynamic `import()`,
  which gives code splitting without a bundler.
- **Routing:** hash routes (`#/dashboard`). Direct navigation to every page
  works with zero server rewrite configuration.

### Trade-off versus React (the alternative considered)

| | Vanilla ES modules (chosen) | React + Vite (V5-style) |
|---|---|---|
| Runtime payload | 34 KB gzip total | ~150 KB+ gzip framework alone |
| Toolchain to run | none | Node + build step |
| Component reuse | pure functions + small DOM helpers | JSX components |
| Fits Phase-3+ complex UI | adequate with discipline | more comfortable at large scale |
| Migration cost later | page-by-page replacement behind `router.js` + `api.js` | — |

The mitigation for vanilla growth pain is a hard rule: **components are pure
functions returning escaped HTML** (`frontend/js/ui/html.js`), unit-tested in
Node without a DOM. If a future phase outgrows this, pages can be replaced
one at a time behind the router and service layer without another
architecture rebuild.

## 3. Backend design

```
backend/
├── app/
│   ├── config.py            # MC6_* env vars, .env loader, database_path
│   ├── logging_setup.py     # application logger + request-id context
│   ├── db.py                # connections, PRAGMAs, migration runner, status
│   ├── migrations/
│   │   ├── 001_initial.sql  # schema version 1
│   │   └── 002_correction_jobs.sql  # durable jobs, files, question rows
│   ├── models.py            # dataclasses, enums, settings definitions
│   ├── storage.py           # the only SQL: records, settings, jobs, results
│   ├── services.py          # SettingsService, StatsService
│   ├── dev_fixtures.py      # deterministic, idempotent development seed
│   ├── engine.py            # engine contract, data types, get_engine()
│   ├── correction/          # Phase 3 engine implementation
│   │   ├── documents.py     # byte validation + PDF/image extraction (pypdf)
│   │   ├── scheme.py        # mark-scheme blueprint extraction
│   │   ├── prompts.py       # marking rules and required JSON shape
│   │   ├── provider.py      # Gemini REST client, bounded retries
│   │   ├── parsing.py       # strict JSON parsing
│   │   ├── validation.py    # marks, maxima, totals, completeness
│   │   ├── verify.py        # numeric/algebraic checks (never edits marks)
│   │   ├── service.py       # orchestration + provider construction
│   │   └── jobs.py          # durable lifecycle, workspace, bounded worker
│   ├── main.py              # FastAPI app: lifespan, routers, middleware, static
│   └── api/
│       ├── deps.py          # storage/settings/stats dependency providers
│       ├── errors.py        # ApiError + shared error envelope
│       ├── error_handlers.py# validation / sqlite / unexpected error handlers
│       ├── system.py        # GET /api/health, GET /api/system/status
│       ├── settings.py      # GET, PATCH /api/settings
│       ├── database.py      # GET /api/database/stats
│       ├── storage.py       # GET /api/storage/summary (bounded walk)
│       └── corrections.py   # submit/list/status/report routes
└── tests/                   # pytest suite
```

Principles:

- **Configuration** is environment-only (`MC6_*`), with an optional `.env`
  read by a ~20-line stdlib loader (process env always wins). Defaults keep
  the app private (`127.0.0.1:8643`). No value is ever logged.
- **Migrations** are numbered `*.sql` files under `app/migrations`.
  `PRAGMA user_version` records the applied version. A database written by a
  newer build is reported as unavailable rather than modified.
- **One storage boundary.** Every SQL statement lives in `storage.py`;
  routes and services never touch `sqlite3` directly.
- **Settings** are typed in `models.py` and validated in one place. The
  current keys are `max_upload_mb` (1–25) and `default_feedback_detail`
  (`brief`/`detailed`). Unknown keys, empty updates and invalid values are
  rejected with a 422 envelope.
- **Responses never leak** secrets, filesystem paths, stack traces or student
  data. Unhandled exceptions return a generic error plus a request id;
  details go to the server log only.
- **Logging** keeps routine health/status checks at DEBUG, logs errors with
  request ids, and never logs request bodies, API keys or submission content.
- **Degraded startup.** If the data directory or database cannot initialize,
  the app still serves the UI and `/api/health`; `/api/system/status` reports
  `database.status = "unavailable"` and data routes answer with a 503
  `database_unavailable` envelope.
- **Static serving** is Starlette `StaticFiles` mounted last, after API
  routes. It enforces path containment (no traversal) and serves
  `index.html` at `/`. The OpenAPI document is available at
  `/api/openapi.json`; the CDN-backed Swagger/ReDoc UIs stay disabled.

### Schema versions 1 and 2

Version 1: `students`, `assignments`, `submissions`, `correction_results` and
`settings`. Version 2 adds `correction_jobs`, `correction_job_files` and
`correction_items` for the durable correction workflow. Rules encoded in both
the schema and `storage.py`:

- Marks are `NULL` only when absent; **zero is a real mark**.
- `missing`, `draft`, `submitted`, `graded` and `failed` submissions are
  distinct; missing/draft cannot receive a correction result, and `graded` is
  reached only by recording a result.
- Lesson codes are stored exactly as supplied (`CH1L1`, `CH1L13`) and are
  never parsed or normalised.
- One correction result per submission, enforced by a UNIQUE constraint and a
  deliberate conflict error.
- A correction job is `queued` before any provider call, moves atomically to
  `processing`, and may reach `completed` only in the transaction that inserts
  all question rows. A failed job cannot be overwritten by a later completion.
- Job file rows store metadata only. Uploaded bytes live in a per-job
  workspace and are deleted on every terminal path.
- Idempotency keys have a partial UNIQUE index, so concurrent retries cannot
  create duplicate jobs.

## 4. Frontend design

```
frontend/
├── index.html
├── css/            tokens.css → base.css → layout.css → components.css
├── js/
│   ├── main.js     # bootstrap: shell + router + status chip + version label
│   ├── router.js   # pure route resolution + dynamic-import page loading
│   ├── api.js      # service layer — THE integration seam
│   ├── store.js    # validated localStorage preferences (harmless data only)
│   ├── icons.js    # locally bundled inline SVG (no icon CDN)
│   ├── ui/         # html, button, card, badge, form, table, states,
│   │               # modal, toast, tabs, pagination
│   ├── layout/shell.js  # sidebar + top bar + drawer + active state
│   └── pages/      # dashboard, correction, settings, storage, tasks, notfound
└── tests/          # node --test, zero dependencies
```

Rules that keep this maintainable:

1. **Escaped by default.** `html` tagged templates escape every interpolation;
   raw HTML must be wrapped in `raw()`. Components compose at any depth.
2. **Pure render, isolated behaviour.** `render()` functions are pure and
   testable in Node; DOM wiring lives in `mount()` functions.
3. **One service layer.** Pages never call `fetch()`; they call `api.js`.
4. **Design tokens only.** Component CSS never hard-codes palette values;
   everything comes from `tokens.css`.
5. **Honest states.** Empty, loading, error and disabled states are shared
   components; disabled future actions carry a visible explanation.
6. **Live data, no sample data.** Dashboard counts and readiness come from
   `/api/database/stats` and `/api/system/status`; the shell version label
   comes from the same status response. Settings reads and writes
   `/api/settings`, while browser-only preferences stay in localStorage.

## 5. Dependency budget (measured)

| | Count | Notes |
|---|---|---|
| Runtime (direct) | **4** | `fastapi`, `uvicorn`, `python-multipart` (browser uploads), `pypdf` |
| Database | **0** | standard-library `sqlite3` |
| AI transport | **0** | standard-library `urllib`; no provider SDK |
| Dev | 2 | `pytest`, `httpx` |
| Frontend runtime | **0** | no npm packages at all |

Frontend payload and startup measurements are recorded in
`phase-1-report.md` and `phase-2-report.md`.

## 6. Integration boundary for later phases (important)

Correction logic must **not** be copied into page components. The seam is
`backend/app/engine.py` (data types, the `CorrectionEngine` protocol, the
input policy, `get_engine()`), backed by `backend/app/correction/`.
`docs/correction-engine-contract.md` is the executable + behavioral contract.

Phase 3 implements the engine; Phase 4 adds the durable job layer without
changing the engine contract. The engine's process-local registry is no longer
the source of truth for results — `Storage` is.

| Feature | Backend seam | Frontend seam |
|---|---|---|
| Correction jobs (Phase 4, **implemented**) | `backend/app/api/corrections.py` → `CorrectionJobService` → Phase 3 engine; migration `002`; report persisted through `Storage` before completion | `api.js` `corrections.*`; `pages/correction.js` upload/job/results tabs; `pages/dashboard.js` recent jobs |
| Google Classroom | `backend/app/api/classroom.py` + provider module; OAuth material server-side only | Settings' Classroom placeholder section + a future page routed via `router.js` |
| Report files | `backend/app/api/reports.py`; generated files under the data directory; must read persisted items only | new page module; Storage page already has a "Reports" category |
| Background tasks UI | Job persistence exists; the Task Manager remains an honest overview | `pages/tasks.js` shows correction-job guidance and planned categories |

Contract rules for Phase 4+ work:

- New features add API routers under `backend/app/api/` — `main.py` only
  registers them.
- New tables arrive as numbered migrations; never edit `001_initial.sql`
  after release.
- Secrets arrive via `MC6_*` environment variables; the browser never sees
  them.
- Every new user-visible capability gets: real states (empty/loading/error),
  automated tests at both layers, and an update to the feature flags in
  `api/system.py` (which drive the Dashboard readiness panel).

## 7. Deliberately deferred after Phase 4

Downloadable report files, Edexcel grades, Classroom sync, provider-key
rotation/management, authentication, class/roster grouping, multi-process or
distributed workers, and deployment automation. The UI labels each as planned
instead of simulating it. `features.reports` stays false until report files
work end to end.

## 8. Correction-engine architecture (Phase 3)

- **One seam.** `get_engine()` dispatches on `MC6_AI_API_KEY`; callers depend
  only on `CorrectionEngine`.
- **Documents first.** Every byte is validated before the provider is called;
  PDFs are read with pypdf and page text is preserved. Corrupt, encrypted or
  mislabelled files fail the job instead of being skipped.
- **Mark scheme is mandatory.** A conservative blueprint (labels + maxima)
  is extracted from the scheme text and used for coverage and maximum
  reconciliation. Extraction never blocks marking; unverified coverage is
  reported.
- **Question-level truth.** The model returns one `MarkedItem` per label.
  Missing questions become `unresolved`, never zero. Unknown maxima keep the
  total unknown and suppress the percentage.
- **Deterministic checks never edit marks.** Numeric/algebraic checks add
  evidence and review flags; totals and percentages are always recomputed by
  Python.
- **Provider isolation.** The Gemini REST client uses stdlib `urllib`,
  bounded retries, a 12 MB raw inline budget and safe error messages. No secret,
  path or student content is logged.
- **Blocking work runs off the event loop** via `asyncio.to_thread`, with at
  most two concurrent provider calls per process.

### Job layer (Phase 4)

- `POST /api/corrections` validates multipart inputs, writes a per-job
  workspace, extracts each document to reject corrupt/encrypted/mislabelled
  bytes, inserts a `queued` row, then starts a daemon worker. The route is thin;
  `CorrectionJobService` owns the sequence.
- A bounded semaphore (`2` workers) limits concurrent jobs; the engine also
  limits provider calls. A queued job waits honestly rather than showing fake
  percentage progress.
- `queued → processing → completed | failed` transitions are atomic storage
  operations. Completion inserts every question row and report total in the
  same transaction that sets the status.
- The workspace is removed in a `finally` block for success, failure and
  unexpected exceptions. Startup reconciliation fails jobs left active by a
  crash and prunes their workspaces.
- The API returns filenames, sizes and roles — never server paths or pasted
  mark-scheme text. Report retrieval reads SQLite only; it does not call the
  provider.
- Single-process assumption: the daemon workers and startup reconciliation are
  designed for one uvicorn process. Running multiple application processes
  would require an external queue/lease and is explicit non-goal work.
