# Math Checker V6 — Phase 8 Test Report

**Date:** 2026-10-19 · Companion: [PHASE_8_AUDIT.md](PHASE_8_AUDIT.md),
[RELEASE_NOTES.md](RELEASE_NOTES.md).

## 1. Executed and passed (exit codes captured)

| # | Test | Command | Result | Exit |
|---|---|---|---|---|
| 1 | Full backend suite | `PYTHONPATH=backend .venv/Scripts/python -m pytest backend/tests -q` | **209 passed**, 1 deprecation warning (14.5 s) | 0 |
| 2 | Full frontend suite | `cd frontend && node --test tests/*.test.mjs` | **49 pass / 0 fail** | 0 |
| 3 | E2E walkthrough | `.venv/Scripts/python scripts/e2e_walkthrough.py` | **PASS** (real server + stub provider, 9/10 persisted) | 0 |
| 4 | Port-conflict startup | occupied-port launcher run | exit 1 with clear message (previously: hung/traceback) | 1 (expected) |
| 5 | Startup after fixes | clean `python main.py` runs in suites 3/4 paths + prior clean-install check | healthy | 0 |

## 2. Concurrency verification (new measurement this phase)

A reproducible in-process exercise (`24 threads` against one SQLite storage):

- **20 parallel job creations** → 20 stored rows, all ids unique.
- **Idempotency race**: 10 threads × 5 attempts with the same
  `Idempotency-Key` → exactly **1** winner, exactly **1** row for that key
  (no duplicate jobs despite racing inserts/unique-index handling).
- **Concurrent completion race**: 6 threads completing the same job → all 6
  reported `completed` **and** exactly 1 question row was stored (idempotent
  completion semantics hold under concurrency; earlier/terminal-state
  conflicts were additionally covered by unit tests).

This proves the storage boundary upholds its invariants under multi-threaded
load — the strongest evidence available without scaling to multiple processes
(which is out of design scope; see DEPLOYMENT.md §2).

## 3. Not executed / not claimable

| Test | Reason |
|---|---|
| Live Gemini correction accuracy | Paid external API; only the single Phase 4 live run is on record. All automated verification uses the local provider stub. |
| Live Google Classroom round-trip | No credentials in this environment; all Classroom behavior is verified against the deterministic Google/Drive double (23 tests). |
| Actual cloud deployment (Render or any host) | Not performed; the honest deployability analysis is in DEPLOYMENT.md §3. No deployment success is claimed. |
| pip-audit / dependency vulnerability scan | Tool unavailable in this environment. |
| Multi-process / replicated deployment | Explicitly out of architecture scope (documented, not hidden). |

## 4. Regressions caught and fixed during this phase

- Version/phase stamp test expectations were updated with the new release
  stamp (`6.4.0` / Phase 8) — the failing test was errored by the change and
  fixed to assert the new truth; suite returned to 209/209.
- The port-conflict probe initially used `bind()`, which is unreliable on
  Windows (rebinding allowed); caught by the live occupied-port check and
  fixed to a connect-probe. Re-verified: exit 1 with clear message.

## 5. Remaining limitations

See [PHASE_8_AUDIT.md](PHASE_8_AUDIT.md) §4 and
[RELEASE_NOTES.md](RELEASE_NOTES.md). Summary: no live external-service
verification, single-process design, no report-file download, no job
cancellation, Classroom publish not exposed over HTTP.
