# Math Checker V6 — Phase 5 Reliability Report

**Date:** 2026-10-19 · Companions: [PHASE5_AUDIT.md](PHASE5_AUDIT.md),
[PHASE5_TEST_REPORT.md](PHASE5_TEST_REPORT.md).

## 1. Fixed in this phase

### R1 (Critical) — Classroom publish flows used a guessed course id

**Problem:** `_course_of()` derived the Google course id by *splitting the
coursework id on `"_"`*. Google course ids and coursework ids are
independent spaces, so `publish_grade`/`attach_report` would PATCH Google
with a wrong `/courses/{id}/…` URL in production. Tests never caught it
because the fake tolerated any course id (audit defect D1/D4).

**Fix:** course ids are now resolved exclusively from cached sync data
(`Storage.classroom_course_of_submission` →
`Storage.classroom_course_of`, added to [storage.py](backend/app/storage.py))
and the parse-based helper was removed
([service.py](backend/app/classroom/service.py)). When nothing is cached the
operation fails honestly with `course_unresolved` and **no Google call is
attempted**.

**Verification:** three new tests — cached-course addressing asserts the
exact PATCH URL, unresolved-course test asserts zero HTTP calls, plus the
publish-setup fixtures now sync first like production must.

### R2 — Failure classification for transient Classroom outages

429/5xx now have direct tests proving they are recorded as `failed` ops with
`rate_limited`/`google_error` codes and user-safe messages — bounded,
non-retried (each publish attempt either lands or records why it did not;
no infinite retry loops on permanent failures).

### R3 — Fractional marks through the persistence boundary

New test proves 0.25/0.5-mark schemes survive validation → storage → report
reconstruction with consistent totals/percentage, that completion is
idempotent (no duplicate rows on a repeated completion) and that a completed
job can never revert states (`ConflictError`).

### R4 — Cosmetic hardening

- Replaced fragile `locals().get("drive_file_id")` in `attach_report` error
  paths with a variable scoped at the failure site.
- The best-effort Drive share step no longer uses a redundant exception
  tuple; it is explicitly cosmetic and can never fail the verified publish
  operation.

## 2. Remaining risks (documented, not silently ignored)

| Risk | Status |
|---|---|
| Real-model marking accuracy | Unknown; known-answer fixtures verified, independent evaluation dataset still future work |
| Live Classroom round-trip | Only mockable; simulated via fake Google endpoints. First live connect should be done against a test course |
| Classroom publish routes not exposed over HTTP | Deliberate: service-layer API exists and is tested; UI wiring is future work. Marked as a Phase-flat boundary, not a defect |
| Single-process job assumptions | Unchanged from Phase 4 (documented non-goal: multiple uvicorn workers need an external lease) |
| pip-audit / dependency scanning | Not available in this environment; recommendation recorded |
| Restarts fail active jobs (no resume) | Honest, safe, documented in Phase 4 |

## 3. Reliability assessment

- **Data integrity:** strongest layer — every report is validated twice
  (engine validation + `_validate_report_for_storage`), totals are
  recomputed, terminal states are immutable, migrations are versioned and
  refuse newer schemas. Verified by tests including the new fractional case.
- **Job reliability:** idempotent submission, bounded workers, restart
  reconciliation, workspace cleanup on every terminal path — all covered by
  tests; the E2E walkthrough exercises the real server path.
- **External failures:** AI provider (bounded retry with backoff, retryable
  classes only) and Classroom (honest op recording, no guessing) both
  degrade predictably; no fabricated results anywhere.
- **Overall:** the integration is understood end-to-end and reproducibly
  verified offline. Phase 5 criteria §13 are met short of the two live-
  credential verifications and real-model accuracy evaluation listed above.
