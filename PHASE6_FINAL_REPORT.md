# Math Checker V6 — Phase 6 Final Report

**Date:** 2026-10-19 · **Release status: READY WITH LIMITATIONS**

Companions: [PHASE5_AUDIT.md](PHASE5_AUDIT.md),
[PHASE5_TEST_REPORT.md](PHASE5_TEST_REPORT.md),
[PHASE5_RELIABILITY_REPORT.md](PHASE5_RELIABILITY_REPORT.md),
[CLASSROOM_CONFIGURATION.md](CLASSROOM_CONFIGURATION.md).

---

## 1. Overall release status

**READY WITH LIMITATIONS.** The application starts cleanly from the documented
procedure, the full correction workflow works end-to-end through the real
server and browser, existing data survives restarts, critical regression
tests pass (backend 207, frontend 49), and no known critical/high defect
remains. The limitations are explicit (§6) — none blocks safe or fundamental
operation.

## 2. Features verified against the actual implementation

| Feature | State |
|---|---|
| UI: all five pages load, navigate, honest states; state persists across navigation | **Implemented and tested** (tests + live browser walk in Phase 5/6) |
| Upload → durable job → real engine → validated persistence → report reading | **Implemented and tested** (API tests + reproducible E2E walkthrough, exit 0) |
| Marks/totals/percentage consistency at every layer; partial vs completed distinction | **Implemented and tested** (validation + storage-boundary tests, fractional-marks case) |
| Restart persistence (settings + completed jobs; interrupted jobs honestly failed) | **Implemented and tested** (unit tests + Phase 6 live restart check) |
| Idempotent submission; no duplicate jobs/uploads; immutable terminal states | **Implemented and tested** |
| Provider failure classes (auth, rate limit, timeout, truncation, safety block) bounded retries | **Implemented and tested** (doubles; no live paid calls) |
| Classroom OAuth/connect/disconnect, course/coursework/submission sync caches, publish-op audit trail, correct course-id addressing, canonical in-place re-correction | **Implemented and tested at the service layer with mocks** — not exercised against live Google |
| Classroom publish over HTTP (grade/attach/return routes) | **Partially implemented** (service-layer only; no browser routes yet) |
| Downloadable report files | **Not implemented** (`features.reports` false; documented) |
| Dev fixtures / seed | **Implemented and tested** (`--seed-dev`) |

## 3. Tests executed (commands and results)

| Command | Result | Exit |
|---|---|---|
| `PYTHONPATH=backend .venv/Scripts/python -m pytest backend/tests -q` | **207 passed**, 1 deprecation warning (14.45 s) | 0 |
| `cd frontend && node --test tests/*.test.mjs` | **49 passed / 0 failed** (0.26 s) | 0 |
| `.venv/Scripts/python scripts/e2e_walkthrough.py` | **PASS** — real server + local provider stub; 9/10 (90%), persisted | 0 |
| Clean-install + restart check (fresh data dir, `main.py`, PATCH settings, restart, assert persistence) | **PASS** | 0 |
| Browser verification (Phase 5, screenshots preserved): results page, evidence disclosure, reload-persistence | **PASS** | — |

All automated tests are offline (no paid APIs, no network beyond
`127.0.0.1`). **Correction-engine evaluation:** the fixed known-answer set
(bundled V5 fixtures + marking fixtures: full-mark, partial-credit, wrong
final value, missing/unreadable, malformed model output, boundary maxima,
fractional marks) passes in full. There was **one** live-provider run ever
(recorded in Phase 4, 9/10). No accuracy percentage is claimed beyond these
discrepancy-free known cases; an independent evaluation dataset is future
work.

## 4. Defects discovered and fixed

Phase 6 found no new correctness defects. The fixes applied were honesty-of-
interface and documentation repairs:

1. **Settings page Classroom card was a disabled "Planned · later phase"
   placeholder with a dead input** although the integration now exists.
   Replaced with real setup guidance pointing at
   [CLASSROOM_CONFIGURATION.md](CLASSROOM_CONFIGURATION.md); the duplicate
   status slot was dropped and the test updated to assert the new truth.
2. **README claims were stale** (Phase 4 framing, schema version 2, no
   Classroom API list, old project tree). Updated to the actual Phase 6
   implementation.
3. **`.env.example` mis-described `MC6_GOOGLE_OAUTH_CLIENT`** as "later
   phase" secret-adjacent config; now documents what it actually is (the
   OAuth client-secret JSON, materialised into the git-ignored data dir).

Earlier phases' documented fixes (course-id resolution R1, failure
classification R2, fractional marks R3, scoping R4) remain verified by their
regression tests.

## 5. Security and data-protection findings

- No hardcoded credentials exist in application code (pattern sweep clean);
  `.env`, `data/`, and `data/secrets/**` are git-ignored and verified
  git-check-ignore positive.
- Uploads: magic-byte + structure checks, generated storage names, bounded
  copy, workspace removal on every terminal path; no path traversal
  (`_workspace` root containment tested).
- Secrets never reach logs, API responses or browser storage (tested).
- Docs UIs disabled; only the OpenAPI document is exposed. No debug
  endpoints exist (`MC6_DEBUG` only raises log verbosity).
- Static Student PDF fixtures are synthetic; no real student data is used.
- No formal security audit performed; no standard-compliance claim is made.

## 6. Remaining defects and workarounds (severity classified)

| Issue | Severity | Workaround |
|---|---|---|
| Correctness of live-model marking beyond the fixed known-answer set is unevaluated | High (accuracy, not correctness) | Treat every report as provisional; review flags included for uncertain questions |
| Classroom publish ops not exposed over HTTP | Medium | Use at service/API-script level or wait for routes; sync + status routes work |
| Restarts fail (do not resume) active jobs | Medium (documented design) | Resubmit; queued work beyond a restart is honestly reported as failed |
| Single-process deployment (no multi-worker lease) | Medium (documented design) | Run one instance as intended; do not scale behind a load balancer |
| Live Google Classroom round-trip unverified | Medium (credentials unavailable in this environment) | All service behaviour verified against controlled doubles; first live connect should use a test course |
| Downloadable report files absent | Low | On-screen report is complete |
| pip-audit/dependency scanning not available in this environment | Low | Pin via `requirements*.txt`; run an audit tool in the deployment environment |

No Critical or High-severity **defects** remain; the accuracy item above is a
knowledge limitation, not a verified defect.

## 7. Deployment and distribution readiness

- **Development config:** `.env` optional debug key; **production config:**
  environment overrides `.env`; [.env.example](.env.example) contains
  placeholders only and is committed while real `.env` files are ignored.
- Startup (`python main.py [--port/--host/--version/--seed-dev]`) verified
  repeatedly, including on a fresh data directory; shutdown is SIGTERM-clean
  (terminate → wait verified in the E2E script and clean-install check).
- Jobs and storage are single-process SQLite/App dirs; a restart reconciles
  active jobs and prunes orphan workspaces.
- Hosting constraints: needs a persistent filesystem for `MC6_DATA_DIR`
  (SQLite + upload workspaces), CPU for PDF rendering, and a provider key;
  it is *not* a static-only serverless deployment. No deployment was
  performed in this environment, so **no live deployment claim is made**.

## 8. Required manual setup steps

1. Python 3.11+; create a venv; `pip install -r requirements-dev.txt`
   (or `requirements.txt` to run only).
2. Set `MC6_AI_API_KEY` (server-side) or `.env`; restart after changes.
3. Optional Classroom sync: place the Google OAuth client JSON at
   `<data>/secrets/google_oauth_client.json` (or set
   `MC6_GOOGLE_OAUTH_CLIENT`), then `POST /api/classroom/connect`.
4. Start: `.venv/Scripts/python main.py` → `http://127.0.0.1:8643`.

## 9. Changed files in this phase (and why)

- [README.md](README.md) — replaced stale Phase 4 claims with the real
  feature state, Classroom API table, schema version 3, current file tree.
- [.env.example](.env.example) — corrected the Classroom client variable's
  description.
- [frontend/js/pages/settings.js](frontend/js/pages/settings.js) — replaced
  the Classroom placeholder card with truthful setup guidance.
- [frontend/tests/pages.test.mjs](frontend/tests/pages.test.mjs) — updated
  assertions to the new truthful card.
- [PHASE6_FINAL_REPORT.md](PHASE6_FINAL_REPORT.md) — this report.

## 10. Implementation-state distinction (explicit)

- **Implemented and tested:** correction workflow, persistence, jobs,
  settings/storage integration, provider failure classes, Classroom service
  layer (mocked Google), clean-install and restart behaviour.
- **Implemented but not exercised against the real service:** Classroom
  against live Google; real-model accuracy beyond one recorded Phase 4 run.
- **Partially implemented:** Classroom HTTP publish surface.
- **Not implemented:** downloadable report files, auth/multi-tenant.
- **Blocked in this environment:** dependency audit tooling (not installed).

## 11. Prioritized remaining work

1. Independent marking-accuracy evaluation dataset (accuracy, High).
2. Classroom publish HTTP routes (Medium).
3. Optional job resume instead of fail-on-restart (Medium, design decision).
4. Run dependency auditing in the deployment environment (Low).
5. Report-file download (Low).
