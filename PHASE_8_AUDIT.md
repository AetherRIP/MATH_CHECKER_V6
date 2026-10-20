# Math Checker V6 — Phase 8 Audit

**Date:** 2026-10-19 · Companion: [TEST_REPORT.md](TEST_REPORT.md),
[RELEASE_NOTES.md](RELEASE_NOTES.md).

## 1. What was verified in the actual repository (not from docs)

- **Baseline test truth:** backend **209 passed** (exit 0), frontend
  **49 pass / 0 fail** (exit 0), E2E walkthrough **PASS** (exit 0) — all
  rerun this phase with exit codes captured.
- **Entry points:** `main.py` (launcher, argparse, sys.path injection),
  `backend/app/main.py` (FastAPI app, lifespan, static mount last),
  `frontend/js/main.js` (zero-build SPA), storage via
  `backend/app/storage.py` (single SQL boundary), engine via
  [engine.py](backend/app/engine.py) protocol, Classroom via
  [service layer](backend/app/classroom/service.py).
- **No dead code / stale references:** no TODO/FIXME debris in `backend/app`;
  the only V5 mention is the provenance comment in `classroom/__init__.py`
  (documentation, not a code path). Port references are uniformly 8643 (V5's
  8642 is gone). No developer-absolute paths.
- **Phase 1–7 deliverables exist and work:** all report files present
  (PHASE5_*, PHASE6_FINAL, PHASE7_INTEGRATION, CLASSROOM_*), the E2E script
  runs, migrations 001–003 initialize schema 3, Classroom/Classroom 23 tests
  green, correction pipeline verified through real server + stub provider.

## 2. Discovered blockers and their disposition

| # | Finding | Severity | Disposition this phase |
|---|---|---|---|
| B1 | Occupied port at startup: launcher hung silently (bind-probe failed on Windows semantics, then uvicorn traceback path) | **High** (blocking for desks/daemons) | **Fixed**: connect-probe before launch; exit 1 with clear, actionable message. Live-verified against an accepting listener. |
| B2 | Startup banner claimed "Classroom arrives in a later phase" (false since Phase 5) and "Phase 4" stamp | Medium (misleading) | **Fixed**: honest Classroom note (points at configuration guide); version stamp → 6.4.0/Phase 8; tests updated |
| B3 | Concurrency behavior never measured (rules §9 requires evidence, not speculation) | Medium | **Measured** (TEST_REPORT §2): parallel create races, idempotency race → 1 winner/row, completion race idempotent. Holds. |
| B4 | No DEPLOYMENT/CONFIGURATION docs committed (deployment readiness was scattered) | Medium | **Fixed**: [DEPLOYMENT.md](DEPLOYMENT.md), [CONFIGURATION.md](CONFIGURATION.md) |
| B5 | Free-tier cloud deploy would silently lose data (ephemeral disk) | High if attempted blindly | **Documented explicitly** in DEPLOYMENT.md §3 (persistent-volume requirement; no deploy performed or claimed) |

## 3. Architecture risks intentionally NOT changed (with evidence)

- **Single-process SQLite storage:** verified to hold correct invariants
  under in-process multithreaded load (B3 measurement). Multi-replica
  deployment is unsupported by design and now says so in DEPLOYMENT.md §2.
- **Interrupted jobs fail on restart rather than resume:** honest, safe;
  a resume design is future-work, not an unplanned rewrite.
- **Correction engine untouched:** no marking-rule or validation change was
  justified by evidence this phase; existing thresholds/review behavior
  preserved.

## 4. Remaining limitations (not fixed, documented)

1. Live Gemini marking accuracy beyond the Phase 4 single live run —
   unevaluated (needs an independently reviewed dataset).
2. Live Google Classroom round-trip including OAuth edge cases — unverified
   (needs credentials + a throwaway test course).
3. Report-file download not implemented (`features.reports` false).
4. Classroom publish operations not exposed over HTTP.
5. Job cancellation not supported (lifecycle lacks a cancel path).
6. Dependency-vulnerability scanning unavailable locally (pip-audit).
7. Cloud deployment itself — feasible with a persistent volume but requires
   real deployment testing before any claim.

## 5. Release assessment (evidence-based)

**Local single-user use: READY** (B1–B4 resolved; verified workflow;
persistency confirmed). **Cloud: not performed** — analysis in
DEPLOYMENT.md; would need a persistent volume and explicit restart-behavior
acknowledgment. Remaining items above are follow-up work, none of which were
concealed or marked done.
