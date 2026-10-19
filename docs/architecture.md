# Math Checker V6 — Architecture

**Phase 1 · Foundation & UI Framework**

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
   TypeScript, 20+ page components) is disproportionate to the UI V6 needs,
   and the brief explicitly asks to evaluate a lighter option seriously.
3. Keep V5's correction engine **entirely out of V6 for now**. It integrates
   later through a documented boundary (§6) rather than being copied into
   page components.
4. V5 was left untouched. Its git tree was clean before work began and
   re-verified clean afterwards.

## 2. Chosen stack

```
Browser ── static files ──▶ FastAPI (uvicorn)
   │                            │
   └── JSON (fetch) ──▶ /api/health, /api/system/status, /api/storage/summary
```

- **Backend:** FastAPI + uvicorn. Two runtime dependencies. No database, no
  background workers, no AI clients at startup — the process is idle until a
  request arrives.
- **Frontend:** vanilla HTML/CSS/ES modules served as static files.
  **No build step.** Pages are fetched on demand via dynamic `import()`,
  which gives code splitting without a bundler.
- **Routing:** hash routes (`#/dashboard`). Direct navigation to every page
  works with zero server rewrite configuration — the right trade-off for
  free-tier hosting and for a tool opened from a local launcher.

### Trade-off versus React (the alternative considered)

| | Vanilla ES modules (chosen) | React + Vite (V5-style) |
|---|---|---|
| Runtime payload | 34 KB gzip total | ~150 KB+ gzip framework alone |
| Toolchain to run | none | Node + build step |
| Component reuse | pure functions + small DOM helpers | JSX components |
| Fits Phase-2+ complex UI | adequate with discipline | more comfortable at large scale |
| Migration cost later | page-by-page replacement behind `router.js` + `api.js` | — |

The mitigation for vanilla growth pain is a hard rule: **components are pure
functions returning escaped HTML** (`frontend/js/ui/html.js`), unit-tested in
Node without a DOM. If a future phase outgrows this, pages can be replaced
one at a time behind the router and service layer without another
architecture rebuild.

### Risk noted and resolved

Python 3.14 wheel availability for pydantic was checked before committing to
the stack; FastAPI 0.146 + pydantic 2.14 install cleanly (verified). No
fallback to Starlette-only was needed.

## 3. Backend design

```
backend/
├── app/
│   ├── config.py      # MC6_* env vars, minimal .env loader, app constants
│   ├── main.py        # FastAPI app: lifespan, routers, error handler, static mount
│   └── api/
│       ├── system.py  # GET /api/health, GET /api/system/status
│       └── storage.py # GET /api/storage/summary (bounded walk)
└── tests/
```

Principles:

- **Configuration** is environment-only (`MC6_*`), with an optional `.env`
  read by a ~20-line stdlib loader (process env always wins). Defaults keep
  the app private (`127.0.0.1:8643`). No value is ever logged.
- **Responses never leak**: no secrets, no filesystem paths, no stack traces.
  Unhandled exceptions return a generic error plus a request id; details go
  to the server log only.
- **Storage summary** walks *only* the application data directory, with hard
  bounds (entry budget + depth limit) and a `truncated` flag so it can never
  become expensive work. Numbers are computed on request — nothing polls or
  scans in the background.
- **Static serving** is Starlette `StaticFiles` mounted last, after API
  routes. It enforces path containment (no traversal) and serves
  `index.html` at `/`. Unknown paths 404 honestly (the SPA uses hash
  routes, so no rewrite fallback is needed).
- Interactive Swagger/ReDoc UIs are disabled (they load from a CDN); the
  OpenAPI document remains at `/api/openapi.json` for future integrations.

## 4. Frontend design

```
frontend/
├── index.html
├── css/            tokens.css → base.css → layout.css → components.css
├── js/
│   ├── main.js     # bootstrap: shell + router + status chip + error hooks
│   ├── router.js   # pure route resolution + dynamic-import page loading
│   ├── api.js      # service layer — THE integration seam for later phases
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
   everything comes from `tokens.css` (colors, spacing, radii, type, motion).
5. **Honest states.** Empty, loading, error and disabled states are shared
   components; disabled future actions carry a visible explanation.

## 5. Dependency budget (measured)

| | Count | Notes |
|---|---|---|
| Runtime (direct) | **2** | `fastapi`, `uvicorn` |
| Runtime (transitive, installed) | 14 total | starlette, pydantic, pydantic-core, h11, click, anyio, … |
| Dev | 2 | `pytest`, `httpx` |
| Frontend runtime | **0** | no npm packages at all |

Frontend payload: **105 KB raw / 34 KB gzip** for the entire application
(HTML + CSS + JS). Full measurements in `phase-1-report.md`.

## 6. Integration boundary for later phases (important)

The correction engine must **not** be copied into page components. The seams
are already in place:

| Future feature | Backend seam | Frontend seam |
|---|---|---|
| AI correction | new `backend/app/api/correction.py` router + engine module behind a service interface | `api.js` gains `correction.*` calls; `pages/correction.js` fills its existing jobs/results tabs |
| PDF processing | engine module (reuse V5's `engine/pdf_inspect.py` ideas) invoked from the correction service | existing file-selection flow uploads its draft |
| Google Classroom | `backend/app/api/classroom.py` + provider module; OAuth material server-side only | Settings' Classroom placeholder section + a future page routed via `router.js` |
| Reports / grading | `backend/app/api/reports.py` | new page module; Storage page already has a "Reports" category |
| Background tasks | job queue module with an API; **no polling** — status endpoints + optional SSE later | `pages/tasks.js` already shows the four task categories |

Contract rules for Phase 2+ work:

- New features add API routers under `backend/app/api/` — `main.py` only
  registers them.
- Secrets arrive via `MC6_*` environment variables; the browser never sees
  them.
- Every new user-visible capability gets: real states (empty/loading/error),
  automated tests at both layers, and an update to the feature flags in
  `api/system.py` (which drive the Dashboard readiness panel).

## 7. What was deliberately left out of Phase 1

AI correction, Gemini/provider integration and key rotation, PDF extraction,
mark-scheme verification, grading, Classroom sync, report generation,
background workers, authentication, databases, deployment automation. The UI
labels each as planned instead of simulating it.
