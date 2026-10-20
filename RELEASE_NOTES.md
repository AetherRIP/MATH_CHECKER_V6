# Math Checker V6 — Release Notes (v6.4.0, Phase 8)

**Date:** 2026-10-19 · Evidence: [TEST_REPORT.md](TEST_REPORT.md),
audit trail in [PHASE_8_AUDIT.md](PHASE_8_AUDIT.md).

## Release readiness decision

| Use case | Verdict |
|---|---|
| **Local single-user use** (teacher's own machine, own data dir) | **READY** — verified end-to-end: installation, startup, occupied-port handling, correction workflow, persistence across restarts, offline reproducible E2E. |
| **Cloud deployment** | **READY WITH SIGNIFICANT LIMITATIONS** — requires a persistent volume for `MC6_DATA_DIR`; no deployment was actually performed here, and deployability analysis (not proof) is in [DEPLOYMENT.md](DEPLOYMENT.md) §3. |
| **Live external-service guarantees** (Gemini accuracy, Classroom round-trip) | **NOT READY TO CLAIM** — verified against controlled doubles only; live credentials were never available in this environment. |

## Changes in v6.4.0 (Phase 8)

1. **Clear occupied-port startup failure** — the launcher now probes the
   configured port with a connect attempt (bind probes are unreliable on
   Windows) and exits 1 with an actionable message instead of uvicorn's
   mid-startup traceback/hang. [main.py](main.py)
2. **Honest startup banner** — removed the stale "Classroom arrives in a
   later phase" message; start output now points at
   [CLASSROOM_CONFIGURATION.md](CLASSROOM_CONFIGURATION.md) when Classroom is
   unconfigured. [main.py](main.py)
3. **Version/phase stamp updated** to 6.4.0 / Phase 8 across
   [config.py](backend/app/config.py), [frontend/package.json](frontend/package.json)
   and the affected tests.
4. **Concurrency verification added** (reported in
   [TEST_REPORT.md](TEST_REPORT.md) §2): 20 parallel job creations, 10-thread
   idempotency race (1 winner, 1 row), 6-thread completion race (idempotent,
   1 stored item) — all passed against the real SQLite storage boundary.
5. **[DEPLOYMENT.md](DEPLOYMENT.md)** (new): local verification results,
   single-process constraint, free-tier cloud blockers and the minimum
   changes needed (persistent volume; no replicas against one data dir).
6. **[CONFIGURATION.md](CONFIGURATION.md)** (new): operational config rules,
   secrets handling, honest provider-limits statement (no "unlimited free AI"
   claims).
7. **[TEST_REPORT.md](TEST_REPORT.md)** (new) and
   [PHASE_8_AUDIT.md](PHASE_8_AUDIT.md) (new): what ran, what could not.

No correction-engine semantics, marking rules, or UI design were changed in
this phase.

## Known issues / limitations (unchanged, documented)

- Report files are not downloadable (`features.reports` false); the on-screen
  report is complete.
- Classroom publish operations exist only at the service layer (no HTTP
  routes); classes/roster edges depend on live verification.
- A restart fails (does not resume) active/queued jobs; they are reported
  honestly with workspaces cleaned.
- Single-process design: one process per data directory; no replicas.
- Live external-service behavior and dependency-audit tooling remain
  unverified in this environment.

## Manual steps before any release to others

1. Run the offline verification:
   `.venv/Scripts/python scripts/e2e_walkthrough.py` (must be PASS, exit 0).
2. Provide `MC6_AI_API_KEY` through the server environment (never committed).
3. Optional Classroom: follow
   [CLASSROOM_CONFIGURATION.md](CLASSROOM_CONFIGURATION.md) and test against
   a throwaway course first.
4. If exposing beyond localhost: HTTPS proxy, explicit `MC6_HOST=0.0.0.0`,
   ≤25 MB multipart allowance, and a backup of the data volume.
