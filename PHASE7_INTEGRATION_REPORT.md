# Math Checker V6 — Phase 7 System Integration Report

**Date:** 2026-10-19 · Deliverables A–F per the Phase 7 request.

Companion reports: [PHASE6_FINAL_REPORT.md](PHASE6_FINAL_REPORT.md) (release
status, deployment readiness), [PHASE5_RELIABILITY_REPORT.md](PHASE5_RELIABILITY_REPORT.md)
(earlier fixes), [CLASSROOM_MIGRATION.md](CLASSROOM_MIGRATION.md).

---

## A. Integration report

### Components inspected this phase

| Component | Interface check | Status |
|---|---|---|
| UI pages → `api.js` → backend routes | Endpoint table in README verified against routers | **Integrated** |
| Settings page ↔ `/api/settings` | Save persists across restart (verified live in Phase 6) | **Integrated** |
| Correction upload → job service → engine → SQLite → report | Full-path API tests + E2E walkthrough | **Integrated** |
| Job lifecycle / states | `queued → processing → completed/failed`, immutability tested | **Integrated** (no cancellation; documented) |
| Classroom service ↔ storage ↔ Google | Sync caches keyed to stable ids; publish flow uses cached course ids (regression-tested since Phase 5 R1) | **Integrated at service layer** (Google = mocked only) |
| Provider ↔ engine | `ModelClient` protocol; bounded retries; failure classes | **Integrated** (no live paid calls) |
| Temporary files | Workspace cleanup on every terminal path; prune at startup | **Integrated** |

### Important changes made

1. **`publish_grade` now records the return locally** — after a successful
   `:return` call the returned Google payload (new state + grades) is written
   through `classroom_replace_submissions`, so the cache shows
   `TURNED_IN → RETURNED` with `previous_state` preserved immediately instead
   of only after the next scheduled sync. Root cause: the cache was never
   updated by the write path, a real state-staleness defect caught by the new
   regression test.
2. **Classroom test double URL matching hardened** — `FakeGoogle` now selects
   the *longest* matching route key and fixture routes were re-anchored. Root
   cause: `/courses/{id}/courseWork` is a prefix of the per-coursework
   submissions URL, so substring matching served the wrong payload
   (coursework list instead of submissions). This is a test-infrastructure
   defect (real Google routes are distinct), but it had masked/complicated
   verification of submission sync; the fix is documented here as a testing
   lesson, not a production bug.

## B. Bug-fix report (significant fixes)

| Fix | Original problem | Root cause | Change | Verification |
|---|---|---|---|---|
| Return-state sync | Cache kept `TURNED_IN` after a successful return | Write path never persisted the returned payload | `publish_grade` writes the `:return` result through `classroom_replace_submissions` when the state changed | New test `test_return_records_previous_and_current_state` (TURNED_IN→RETURNED, `previous_state` preserved, grades cached) |
| Zero-grade caching | None: verified explicitly against V5 regression class "zero grade dropped" | — | Regression test `test_zero_grade_is_a_real_grade_not_a_missing_one` proves 0.0 is written and re-synced as a real grade (never NULL/missing) | New test passes |
| Prefix-matching fake | Submissions list came back empty in new tests | Substring route matching with a shared prefix served the wrong payload | Longest-match selection in `FakeGoogle` + re-anchored fixture keys | 23/23 classroom tests pass; reproduced and confirmed the wrong-payload cause before fixing |

## C. Test report

| Suite | Command | Result | Exit |
|---|---|---|---|
| Backend (all) | `PYTHONPATH=backend .venv/Scripts/python -m pytest backend/tests -q` | **209 passed**, 1 deprecation warning (14.6 s) — up from 207 | 0 |
| Frontend (all) | `cd frontend && node --test tests/*.test.mjs` | **49 pass / 0 fail** | 0 |
| E2E | `.venv/Scripts/python scripts/e2e_walkthrough.py` | **PASS**, 9/10 persisted | 0 |

- **Tests added this phase (backend +2):** the two Classroom regression tests
  above. Classroom file now 23 tests, all passing.
- **Skipped:** none. No test was disabled or weakened.
- **Mocked vs real:** all external services (Gemini provider, Google
  Classroom/Drive) are exercised through local test doubles only. Live
  credentials were never available in this environment, so **no live
  external-service success is claimed**.

## D. Remaining issues

Confirmed defects: **none outstanding** (all known defects from Phases 5–6
remain fixed under regression tests: 207 + 2 passing).

Suspected but unverifiable here (not defects):
- Live Gemini marking accuracy beyond the known-answer fixtures.
- Live Google Classroom round-trip behavior (OAuth edge cases, real rate
  limits). First live connect should be done against a throwaway test course.

Inherited limitations (documented, unchanged): Classroom publish has no HTTP
routes; restart fails active jobs by design; single-process deployment;
report-file download not implemented; pip-audit unavailable locally.

## E. Deployment readiness checklist

Verified (Phase 6, unchanged this phase): clean install on a fresh data dir
starts healthy (schema 3), settings persist across restart (exit-0 script),
`main.py` startup/shutdown clean, port override works, health endpoint
present. Commands:

```
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt
set MC6_AI_API_KEY=<key>   # required for correction only
.venv/Scripts/python main.py            # → http://127.0.0.1:8643
.venv/Scripts/python scripts/e2e_walkthrough.py   # full offline verification
```

Not claimed: any deployment to a hosting provider, and any live Google/Gemini
behavior.

## F. Final repository state

Changed by this phase:
- [backend/app/classroom/service.py](backend/app/classroom/service.py) —
  return-path cache update (the one production change).
- [backend/tests/test_classroom.py](backend/tests/test_classroom.py) — 2 new
  regression tests + longest-match fake + re-anchored fixture keys.
- [PHASE7_INTEGRATION_REPORT.md](PHASE7_INTEGRATION_REPORT.md) — this report.

Everything else is unchanged from the Phase 6 state (see
[PHASE6_FINAL_REPORT.md](PHASE6_FINAL_REPORT.md) §9 for that phase's file
list). No files were removed; no user data touched (all tests use temp dirs).
