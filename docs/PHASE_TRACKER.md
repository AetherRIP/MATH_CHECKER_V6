# MATH V6 — Phase Tracker (recovery audit, 2026-10-20)

**Purpose:** reconcile the repository's *actual* state against the established
8-phase roadmap, after the working tree was found stripped of all source code.
Written to the current branch (`main`). **No phase is claimed complete here
that could not be reproduced from files in this audit.**

**Verdict up front: the roadmap was not abandoned. The full source for Phases
1–8 exists on the `phase-1-foundation` branch (tip `4277755`, identical to
`origin/phase-1-foundation`), released as v6.4.0. Nothing needed to be
rebuilt from scratch.**

---

## 0. Repository state found by this audit

| Item | Finding |
|---|---|
| Branch checked out | `main` (tracks `origin/main`) |
| `main` history | 2 commits: `dce9888` "Initial commit", `fc2bbcd` "Add generated local artifacts" |
| `main` tracked files | Only generated artifacts: `__pycache__/*.pyc`, 3 local `app.db` DBs, `data/secrets/classroom_refresh_token`, `data/tmp/scratch.bin`, `.freebuff/project-id`, LICENSE, README, .gitattributes |
| `main` missing | **All** `.py` source, all tests, all frontend files, all docs — despite the bytecode `.pyc` files proving the modules once existed |
| Branch `phase-1-foundation` | 10 commits `2882122`→`4277755`, **full source recovered here** (backend, frontend, 24 backend test files, 7 frontend test files, docs, scripts, screenshots) |
| Other branches/stashes | none (`git stash list` empty) |
| Shared with remote? | Both `main` and `phase-1-foundation` are pushed to `origin` (github.com/AetherRIP/MATH_CHECKER_V6); local tips equal remote tips |

**Conclusion:** the source was never lost — it lives on `phase-1-foundation`.
`main` was checked out separately and accumulated only generated artifacts
(and, worse, one live-looking secret), then committed and pushed.

---

## 1. What the Phase 2 artifact databases actually establish

Inspected read-only via Python `sqlite3` (`mode=ro`), **not** treated as proof.

| Database | Contents | What it demonstrates |
|---|---|---|
| `data/phase2-fix-check/app.db` | Settings keys `default_feedback_detail`, `max_upload_mb`; **0 students, 0 assignments, 0 submissions, 0 correction_results** | Only that schema version was created; empty operationally. **Proves nothing** about fixes. |
| `data/phase2-retry-check/app.db` | All 5 tables, 0 rows everywhere | Schema creation only. **Proves nothing** about retries. |
| `data/phase2-ui-check/app.db` | 2 settings; 2 fake "seed" students (Ada Lovelace, Grace Hopper); 2 seed assignments; 4 seed submissions (statuses submitted/draft/missing/graded); 1 seed correction result **explicitly labelled "Seed result …"** | This is `dev_fixtures` seed data, not captured user data or service evidence. It shows the DB schema the UI reads, **not** a passing test or a working pipeline. |
| `data/phase2-degraded-broken/app.db` | Directory, not a valid SQLite file | Broken artifact; a degraded run was interrupted at creation. Otherwise meaningless. |

**Assessment: the Phase 2 DBs prove nothing by themselves.** They are local
test-run leftovers. They contain no real student data (only `seed-*` fake
fixtures), so there is no personally identifiable content in them — but they
also should not be in git (§4).

---

## 2. Source-code recovery — what was found and verified

`git archive phase-1-foundation | tar -x` into a scratch directory, then:

| Check | Command | Result |
|---|---|---|
| Source compiles | `.venv/Scripts/python.exe -m compileall -q <extracted>/backend/app <extracted>/backend/tests <extracted>/main.py` | exit 0 — no syntax errors anywhere |
| Backend tests | `cd <extracted>/backend && <repo>/.venv/Scripts/python.exe -m pytest tests -q --tb=no -p no:cacheprovider` | **209 passed, 1 Starlette deprecation warning, exit 0, 16.0 s** — independently reproduces the Phase 8 audit's 209-pass baseline from recovered source |
| Frontend tests | `cd <extracted>/frontend && npm test` (Node built-in runner) | **49 pass / 0 fail, exit 0** — matches release claims exactly |
| venv completeness | `python -c "import fastapi, httpx, pypdf, pikepdf"` | present; `fitz` (PyMuPDF) **absent** — did not block any of the 209 tests, noted as a limitation |

Every module present as a `.pyc` on `main` has a corresponding `.py` on
`phase-1-foundation` — the bytecode is the compiled remains of the same
codebase; nothing is orphaned or unrecoverable.

### Recovered vs. still missing

| Component | Status |
|---|---|
| FastAPI backend (`backend/app/**`, 3 SQL migrations) | **Recovered** on `phase-1-foundation` |
| Correction engine `backend/app/correction/**` (9 modules) | **Recovered** |
| Classroom integration (`backend/app/classroom/**`) | **Recovered** |
| 24 backend test files + MATH V5 reference PDF fixtures | **Recovered** |
| Vanilla JS frontend (pages, UI components, router, store) + 7 `node --test` files | **Recovered** |
| Phase docs: `docs/phase-{1,2,3,4}-report.md`, `PHASE5_*`, `PHASE6/7/8`, `RELEASE_NOTES.md`, `TEST_REPORT.md`, `DEPLOYMENT.md`, Classroom docs, `.env.example`, CI workflow | **Recovered** |
| Phase documents/audit on `main` itself | **Still missing** — `main` needs repair (§6) |
| Live (non-mock) Gemini evaluation of the engine | **Never performed** — Phase 3 report states no API key was ever available in that environment |
| Live Classroom round-trip with a real Google account | **Never performed** — verified against controlled doubles only |
| Actual cloud deployment | **Never performed** — Phase 8: "READY WITH SIGNIFICANT LIMITATIONS" |

---

## 3. Credential exposure — Google Classroom refresh token

**Where tracked:** `data/secrets/classroom_refresh_token`, added by commit
`fc2bbcd` ("Add generated local artifacts") on `main` and **already pushed to
`origin/main` on GitHub** (`remotes/origin/main` ≡ `fc2bbcd`). The token bytes
were inspected only for *size*; the value was never read or printed.

- `phase-1-foundation` tracks no `data/` or secrets files; its `.gitignore`
  correctly excludes `.env`, `data/`, `__pycache__`, `.venv`.
- History scan on both branches: **no** `AIza…` keys, **no** PEM blocks, **no**
  literal 60+-char secrets — all `client_secret`/`refresh_token` mentions in
  code/docs are env-var names, docstrings or comments. The committed token
  file is the only credential exposure found.

**Remediation status: NOT yet performed. Necessary steps, in order:**

1. **Rotate/revoke** the Classroom refresh token — treat it as compromised
   from the moment it entered a commit. Revoke via the Google OAuth revoke
   endpoint or Google Account → Security → Third-party access, then re-issue
   by re-running the Classroom OAuth flow afterward; rotate the Desktop-app
   OAuth client secret too if it was ever exposed anywhere.
2. **Rewrite `main` history** with `git filter-repo` (or BFG) to drop
   `data/secrets/`, `__pycache__/`, `.pytest_cache/`, `data/**/app.db`,
   `data/tmp/` and `.freebuff/` from past commits, then force-push `main`.
   This is destructive and is **not executed by this audit** — it needs
   explicit user authorization. `phase-1-foundation` is clean and must not
   be rewritten.
3. Ask GitHub Support to purge cached views of the removed blob (Data
   Recovery); the rotation in step 1 already neutralises the exposure even
   if cached copies persist.

---

## 4. Tracked-artifact hygiene

Once §3's rewrite is done (or the user prefers a forward-only fix), `main`
should stop tracking artifacts:

- `git rm -r --cached __pycache__ backend/app/**/__pycache__ backend/tests/__pycache__ .pytest_cache .freebuff data` then commit.
- Adopt the recovered `.gitignore` — **already added to the working tree by
  this audit as a single safe edit, not committed**. It is byte-identical to
  the version already proven on `phase-1-foundation`.
- `data/phase2-*` databases are seed-artifact only; safe to delete locally
  after §1, but this audit did **not** delete anything.

---

## 5. Phase-by-phase status against the established roadmap

Statuses: ✅ *Verified* = reproduced in this audit; 🟡 *Partially verified* =
documented evidence only, not reproducible here; ⚪ *Unverified*; ❌ *Missing*.

| Phase | Scope | Status | Evidence / notes |
|---|---|---|---|
| 1 | UI foundation, navigation, reusable components, layouts, themes, placeholder pages | ✅ Verified | `docs/phase-1-report.md`; full frontend tree with screenshots recovered; exercised indirectly by the 49 passing frontend tests |
| 2 | Backend foundation, configuration, logging, data models, storage, genuine backend status. No AI correction engine | ✅ Verified | `docs/phase-2-report.md`; commits `700f743`, `a900bc1`, `0669159`, `fd4bfae` (audit defects closed). Storage/settings/database/system/degraded tests are among the 209. **No AI engine is present in Phase 2 code**, as scoped. The `data/phase2-*` SQLite files are *not* evidence (§1) |
| 3 | Modular, testable AI math correction engine using MATH V5 as reference | 🟡 Partially verified | `docs/phase-3-report.md`, commit `62d3768`, `docs/correction-engine-contract.md`; 9 engine modules; `test_correction_{engine,jobs,provider,scheme,validation,verify,documents,marking_fixtures}` + `test_v5_reference_fixture.py` with real V5 PDF fixtures pass **offline against a mock provider**. **Never evaluated against live Gemini — no API key was ever available**; marking accuracy remains unverified, exactly as the Phase 3 report itself discloses |
| 4 | Existing Phase 4 spec: upload → durable jobs → engine → persisted results → UI wiring | ✅ Verified (code + tests) | `docs/phase-4-report.md`; durable correction-job migration `002`; jobs/persistence tests among the 209 |
| 5 | Automated testing, reliability, integration verification | ✅ Verified (offline) | `PHASE5_TEST_REPORT.md` + `PHASE5_AUDIT.md` + `PHASE5_RELIABILITY_REPORT.md`: 207 backend + 49 frontend passes, all offline. Independently rerun here from recovered source: 209/49 |
| 6 | Existing Phase 6 spec: verification + documentation | 🟡 Partially verified | `PHASE6_FINAL_REPORT.md` (READY WITH LIMITATIONS) with Classroom config/migration/test docs; Classroom itself only mock-tested |
| 7 | Integration, reliability, production readiness | 🟡 Partially verified | `PHASE7_INTEGRATION_REPORT.md`, Deliverables A–F recorded in the report |
| 8 | Deployment preparation, production hardening, release readiness | ⚪ Unverified / never deployed | `PHASE_8_AUDIT.md` (baseline 209/49 + E2E PASS, rerun as part of the release), `RELEASE_NOTES.md` v6.4.0: local single-user **READY**; cloud **READY WITH SIGNIFICANT LIMITATIONS**; live external-service guarantees **NOT READY TO CLAIM**. No deployment was actually performed |

**Phase 9 has not been started and is not authorised or required by this
audit's findings.** No phase is marked complete beyond what files demonstrate.

---

## 6. Recommended next action, in order

1. **Stop treating `main` as the source of truth** — it currently contains no
   code, only artifacts and a leaked credential.
2. **Get explicit user authorization before any destructive Git operation**
   (history rewrite / force-push). Recommended: after rotating the token,
   rewrite `main` to drop the secret and generated artifacts, then point
   `main` at the recovered tree (merge or fast-forward from
   `phase-1-foundation`). The audit deliberately did **not** rewrite history,
   untrack artifacts, or move branches — that preservation is intentional.
3. Keep the hygiene lock-in: the recovered `.gitignore` (added here), stop
   committing `data/` and bytecode, and note the venv gap: PyMuPDF (`fitz`)
   is missing from `.venv`, harmless today but worth installing.
4. Only then resume normal development. The highest-value verified gap left
   in the whole roadmap is a **live Gemini evaluation of the Phase 3 engine**
   (and a real Classroom round-trip), which have never been run with real
   credentials.
