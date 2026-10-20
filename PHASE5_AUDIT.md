# Math Checker V6 — Phase 5 Baseline Audit

**Date:** 2026-10-19 · **Baseline:** branch `phase-1-foundation`, working tree
contains the uncommitted Phase 3/4 + Google Classrom work.

## 1. Test results before modifications

| Suite | Command | Result |
|---|---|---|
| Backend | `PYTHONPATH=backend .venv/Scripts/python -m pytest backend/tests -q` | **202 passed**, 1 deprecation warning, exit 0 (~14 s) |
| Frontend | `cd frontend && node --test tests/*.test.mjs` | **49 passed**, 0 failed (~0.27 s) |

A clean-start check was also done: everything runs from `MC6_*` env/`.env` only;
no accidental local state is required (verified in §3).

## 2. Implemented functionality (verified by inspection + tests)

- **Phase 1/2 foundations:** FastAPI + SQLite storage boundary, hash-routed
  vanilla-JS frontend, settings/stats/storage APIs, degraded-startup 503
  envelopes, request-id logging. Present and tested.
- **Phase 3 correction engine:** `CorrectionEngine` protocol in
  [engine.py](backend/app/engine.py); pipeline
  documents → scheme blueprint → provider → JSON parse → validation → verify.
  Provider client has bounded retries with backoff (transient-only: 429/5xx/
  transport), never logs bodies or the key, and fails honestly on truncation,
  safety blocks and empty responses.
- **Phase 4 durable jobs:** `CorrectionJobService` with per-job workspaces,
  `queued → processing → completed | failed` lifecycle (terminal states
  immutable in [storage.py](backend/app/storage.py)), idempotency-key dedupe
  (partial UNIQUE index + race handling), bounded workers (2), restart
  reconciliation, report validated **again** at the persistence boundary
  (`_validate_report_for_storage`: totals, maxima, percentages, unresolved
  consistency).
- **Classroom integration (recent, most at risk):** OAuth connect flow,
  course/coursework/submission sync caches keyed to Google stable ids
  (schema v3), publish ops audit trail, canonical-report-in-place semantics.

## 3. Execution-flow trace (UI → backend → engine → storage → external)

`frontend/js/pages/correction.js` → `api.js` (single fetch seam, error-envelope
aware, multipart + `Idempotency-Key`) → `POST /api/corrections` →
`CorrectionJobService.create_job` (validate fields → save upload bytes →
extract to reject bad bytes → `validate_request` → durable `queued` row →
worker thread) → engine `submit` (async, `asyncio.to_thread`) → provider →
`validate_model_output` + `verify_items` →
`Storage.complete_correction_job` (items + totals + `completed` in one
transaction) → report retrieval from SQLite only. **No gaps found in this
flow**; secrets never appear in responses/logs (checked against middleware,
provider, provider stub tests).

## 4. Defects found

| # | Severity | Area | Finding |
|---|---|---|---|
| D1 | **Critical** | Classroom | `_course_of()` in [service.py:368](backend/app/classroom/service.py) derives `course_id` by splitting the coursework id on `"_"` — Google coursework ids are unrelated to course ids, so `patch_grade_fields`/`attach_report` would be called with a **wrong course id** in production. Tests pass only because the fake routes tolerate it. Correct data exists in cache (`classroom_submission_target`, coursework rows); the service must resolve course ids from storage and fail the op honestly if unmapped. |
| D2 | Medium | Classroom API | Publish/grade/attach flows exist in the service but no HTTP routes expose them (`api/classroom.py` only has sync + ops routes). Not a corruption risk, but `link_correction`/publish are dead code from the UI side; document as deliberate Phase 5 boundary. |
| D3 | Low | Classroom service | `attach_report` uses `locals().get("drive_file_id")` to report the file id on failure — fragile but functional; `except (ClassroomApiError, Exception)` is redundant. Cosmetic clean-up only. |
| D4 | Low | Tests | No test asserts the course id actually used in publish calls; `test_publish_grade_success…` would pass even while calling the wrong course (which is how D1 survived). |

## 5. Gaps vs Phase 5 requirements

1. **E2E browser test:** the Phase 4 report documented a manual browser walk
   (with live Gemini!), but no reproducible E2E artifact exists in CI. Gap.
2. **Rounding/aggregation:** totals are recomputed from item marks everywhere
   (validation + storage boundary) — covered. But no explicit test for
   fractional-mark consistency (e.g. 0.5 marks) against the persisted rows.
3. **External-failure coverage for Classroom:** tests cover published/403/auth/
   disabled/verify paths; rate-limit (429) and timeout translation exist in
   `translate_error` but 500/timeout cases are untested.
4. **Restart persistence:** covered by unit tests (`recover_interrupted`),
   but not exercised through the API layer after a simulated restart.
5. **Performance:** Phase 1/2 recorded payload/startup numbers; no regression
   check exists, and no measured memory use during PDF processing.

## 6. Security review snapshot

- Upload validation: magic bytes + page structure + size caps at the
  workspace save (chunked, capped) and again in `validate_request`; filenames
  sanitised (`_clean_filename` takes `Path().name`, rejects `.`/`..`); stored
  paths are generated (`submission-0.pdf`), not attacker-controlled.
- Path traversal: job workspace paths validated against the resolved root
  (`_workspace`); StaticFiles containment confirmed by tests.
- Secrets: noted at source lines that read env keys; no key reaches
  responses/logs (provider log lines print exception class names only);
  Classroom tokens live under `data/secrets/` (git-ignored).
- Debug surface: docs/redoc disabled; only `/api/openapi.json` exposed.
- Temporary files: every terminal path calls `_cleanup_workspace`; prune
  removes orphan workspaces at startup.

## 7. Recommended fixes (order)

1. Fix D1 (course-id resolution from storage; fail honestly when unmapped) +
   a regression test that fails if the wrong course id is sent (D4).
2. Add missing external-failure tests for Classroom (500/429) and a
   fractional-marks persistence test.
3. Reproducible E2E artifact: run the real server with a local provider stub
   and drive the browser workflow; record evidence in the test report.
4. Document the publish-route boundary (D2) and clean up D3.

## 8. Prerequisites check

All Phase 1–4 prerequisites exist and pass. No missing dependency, migration
or configuration was found; no silent pretending. Migration chain is intact
(schema v3 = `001` + `002` + `003`); a database written by a newer build is
refused rather than mutated.
