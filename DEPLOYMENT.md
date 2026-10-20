# Math Checker V6 — Deployment Guide

Companions: [CONFIGURATION.md](CONFIGURATION.md), [README.md](README.md)
(setup + troubleshooting). This guide covers what to check when taking V6 to a
machine other than the development one, and honestly assesses cloud hosting.

## 1. Local deployment (verified in this repo)

```bash
# Python 3.11+ (developed and tested on 3.14)
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # run-only
.venv/Scripts/python -m pip install -r requirements-dev.txt # run + tests

set MC6_AI_API_KEY=<key>            # required only for corrections
.venv/Scripts/python main.py        # http://127.0.0.1:8643
```

Verified properties (evidence in [TEST_REPORT.md](TEST_REPORT.md)):

- Fresh data directory initializes schema 3 automatically; no manual SQL.
- Occupied port → exit code 1 with a clear message (not a traceback).
- Settings persist across restarts; completed results survive restarts;
  interrupted jobs are marked failed honestly and their workspaces pruned.
- No absolute developer paths: the launcher resolves `backend/` relative to
  `main.py`; data goes where `MC6_DATA_DIR` points. Nothing is read from any
  V5 directory.
- Offline reproducibility check:
  `.venv/Scripts/python scripts/e2e_walkthrough.py` (exit 0).

## 2. Single-process constraint (read before scaling)

V6 runs correction jobs as bounded daemon threads inside **one** process and
stores everything in the SQLite file in `MC6_DATA_DIR`. This is deliberate:
simple, transactional, zero-dependency. Consequences:

- Run exactly one application process per data directory.
- Multiple uvicorn workers or replicated containers behind a load balancer
  will each claim the same data dir and is NOT supported without a lease
  system that does not exist. Do not deploy replicas against one volume.
- A restart during processing fails active jobs (they are reported honestly,
  not resumed). Queued for a future phase: resumable jobs.

## 3. Cloud deployment assessment (Render or similar)

What works in principle: FastAPI on uvicorn binds `PORT` via `MC6_PORT`
(CLI/env), `/api/health` is a ready-made health check, dependencies install
from `requirements.txt`, host/port config is environment-driven.

Blockers/limits that must be planned for — do NOT assume them away:

| Concern | Reality |
|---|---|
| **Persistent disk** | SQLite + upload workspaces need a persistent volume mounted at `MC6_DATA_DIR`. Free tiers usually have none → **a free-tier deploy would lose data on every restart.** Minimum change: mount a disk, or move storage to a managed DB (requires the storage boundary to speak to it — not implemented). |
| **Background jobs** | Correction jobs are in-process threads. Platform restarts (deploys, sleeps, crashes) kill them mid-run; they will be surfaced as failed, not lost silently. There is no external queue, so long platform request timeouts DO NOT apply to corrections (they run after the HTTP 202), but the worker dies with the process. |
| **Request size** | Uploads up to 25 MB per file; the platform proxy must allow multipart bodies of that size. |
| **Provider quota** | Free-tier Gemini keys are rate-limited; the engine's 2-concurrent-call bound + bounded exponential backoff respects that, but heavy use will fail with `rate-limited` messages honestly. |
| **Secrets** | Provide `MC6_AI_API_KEY` via the platform's environment/secrets UI; never bake it into the image. |

Conclusion: **local use is ready now; small-scale single-user cloud deploys
are feasible ONLY with a persistent volume for `MC6_DATA_DIR` and acknowledged
restart behavior. No cloud deployment was performed or verified in this
environment, and none is claimed.**

## 4. Manual steps before any public exposure

1. Put the app behind a reverse proxy with HTTPS; V6 serves plain HTTP (the
   Launcher binds localhost by default).
2. Set `MC6_HOST=0.0.0.0` explicitly (documented opt-in) only when intended.
3. Configure the platform proxy to allow ≤25 MB multipart uploads.
4. Ensure the data volume is backed up (it is the entire store of record).
