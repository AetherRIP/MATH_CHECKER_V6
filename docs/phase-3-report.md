# Math Checker V6 — Phase 3 Completion Report

**Scope:** mathematical correction engine · **Status:** implemented and
automatically tested; **no live-provider evaluation was possible**
(no API key in this environment) · **Version:** 6.2.0 (Phase 3)

This report describes the engine that actually exists. It does not repeat the
original plan, and it does not claim marking accuracy that was not measured.

---

## 1. Repository audit

### 1.1 What Phase 3 looked like at the start

The repository contained the Phase 3 **contract only**:

- `backend/app/engine.py` — data types, `CorrectionEngine` protocol, input
  policy and `UnavailableEngine`;
- `docs/correction-engine-contract.md` — the behavioural half;
- `backend/tests/test_engine.py` — contract tests.

There was no correction implementation, no provider client, no PDF extraction,
no prompt, no result validation and no marking tests. `get_engine()` returned
`UnavailableEngine` unconditionally. No branch, stash, dangling commit or
sibling working copy in this repository contained prior Phase 3 work.

This pass therefore implemented Phase 3; it did not merely wire something up.

### 1.2 V5 components inspected

| V5 area | Finding | Decision for V6 |
|---|---|---|
| `engine/legacy_marking.py` | Working Gemini marking prompt and JSON schema; totals recomputed in Python; per-question breakdown | Reused the **behavioural rules** (M/A/B, ECF/ISW, no invented working, no fabricated totals) in a new, smaller prompt; did not copy the 992-line module |
| `gemini/client_proxy.py`, `gemini/key_manager.py` | Multi-key rotation, cooling, remote file upload, quota probing | Not reused: V6 has no key-rotation requirement and no SDK. A single-key stdlib REST client is enough and avoids the debt |
| `engine/pdf_inspect.py` | PyMuPDF with pypdf fallback, page counts, question tokens | Reused the **idea** (validate first, keep page numbers, tolerate per-page failures); implemented with `pypdf` only |
| `engine/verify.py`, `engine/result_guard.py` | Deterministic recomputation, never overwrite marks, explicit review states | Reused the **principle** verbatim: deterministic checks never change a mark; only review flags are added |
| `engine/scheme_inventory.py`, `blueprint.py` | Very large scheme-structure analysis | Not reused. V6 extracts only a conservative label/maximum blueprint and reports when it cannot |
| `large_pdf/*` | Batch planning for very large documents | Out of scope; V6 bounds pages and text and rejects an unmarkable payload honestly |
| V6 Phase 1/2 | FastAPI, dataclasses, one storage boundary, `MC6_*` config, error envelope, honest feature flags | Respected; no second config/storage system, no new framework |

V5 was read-only during this phase.

## 2. Implementation summary

The engine accepts student work and a mark scheme, validates both, calls the
configured provider, validates the returned marks and returns a typed
`CorrectionReport`. It never fabricates a result and never converts a failure
into an empty success.

### 2.1 Pipeline

```
validate_request
  → document byte validation + page-aware text extraction (pypdf)
  → mark-scheme blueprint (labels + maxima, conflicts detected)
  → prompt (rules, scheme, extracted text, blueprint)
  → Gemini generateContent (documents inline for visual reading)
  → strict JSON parse (one bounded repair attempt)
  → mark/maximum/coverage validation
  → deterministic numeric/algebraic checks
  → CorrectionReport + CorrectionJob
```

### 2.2 Marking rules enforced

- One result per question label; duplicate labels are rejected.
- A marked question must have a numeric mark.
- Marks are finite, non-negative and never exceed the maximum.
- The mark scheme is mandatory; it can be a PDF/image file and/or pasted text.
- An unambiguous scheme maximum overrides a conflicting model maximum; a weak
  extraction hint never does.
- A question in the blueprint that the model omitted becomes `unresolved`
  with `awarded = null`, never `0`.
- A non-marked question carrying a mark has the mark dropped and the
  contradiction reported.
- Totals are recomputed from accepted item marks. Model-supplied totals,
  percentages and confidence values are ignored.
- A report is `completed` only when every item is `marked`, every item has a
  mark and a maximum, and no blueprint question is missing. Otherwise it is
  `partial`, has no percentage, and lists the unresolved labels.
- Review flags record uncertainty categories; no numeric confidence is
  presented as calibrated probability.

### 2.3 Deterministic verification (never edits marks)

- numeric equality across fractions, decimals, percentages, mixed numbers,
  thousands separators, currency signs, trailing units and `x = …` forms;
- algebraic equivalence by numeric sampling for simple expressions
  (`+ − × ÷ ^ %`, parentheses, `sqrt`, `abs`, `pi`, free variables);
- different free-variable sets, prose answers and unsupported expressions are
  `inconclusive`, not "wrong";
- a matching answer with zero marks, or a differing answer with full marks,
  adds `mark_allocation_review` and a warning. The mark itself is untouched.

### 2.4 Documents

- byte-level media-type checks (a `.pdf` that is not a PDF is rejected);
- existence, non-empty, 25 MB per file, 1–200 pages;
- password-protected PDFs are reported, not silently skipped;
- per-page text extraction with page numbers; logical line breaks are
  preserved (collapsing a page to one line hid every scheme row after the
  first), while spaces within a line are normalised; unreadable pages and
  pages without extractable text are reported;
- 60,000-character document / 12,000-character page extraction bounds with
  truncation warnings;
- a 12 MB raw inline provider budget (~16 MB base64); over-budget documents contribute text, and
  a textless over-budget document fails honestly;
- no temporary files are created and caller-owned files are never deleted
  (asserted by tests). Phase 4 owns upload workspaces and cleanup.

## 3. Files

### Created

| File | Reason |
|---|---|
| `backend/app/correction/__init__.py` | package map |
| `backend/app/correction/documents.py` | byte validation, PDF/image extraction |
| `backend/app/correction/scheme.py` | conservative scheme blueprint |
| `backend/app/correction/prompts.py` | marking rules, JSON contract, repair prompt |
| `backend/app/correction/provider.py` | `ModelClient`, Gemini REST client, retries, safe errors |
| `backend/app/correction/parsing.py` | strict JSON object parsing |
| `backend/app/correction/validation.py` | marks, maxima, coverage, totals, completeness |
| `backend/app/correction/verify.py` | deterministic numeric/algebraic checks |
| `backend/app/correction/service.py` | orchestration, provider construction, process-local registry |
| `backend/tests/pdf_factory.py` | dependency-free real PDF writer for tests |
| `backend/tests/test_correction_documents.py` | document validation/extraction tests |
| `backend/tests/test_correction_scheme.py` | blueprint tests |
| `backend/tests/test_correction_verify.py` | deterministic-check tests |
| `backend/tests/test_correction_validation.py` | result-validation tests |
| `backend/tests/test_correction_engine.py` | pipeline tests with a fake model client |
| `backend/tests/test_correction_marking_fixtures.py` | representative marking decisions and totals |
| `backend/tests/test_correction_provider.py` | real-HTTP client tests + full pipeline over a stub provider |
| `backend/tests/test_v5_reference_fixture.py` | authentic V5 fixture run end to end with reference marks replayed |
| `backend/tests/fixtures/v5/*.pdf` | the two authentic V5 synthetic fixture PDFs (2.8 KB total) |
| `docs/phase-3-report.md` | this report |

### Modified

| File | Change |
|---|---|
| `backend/app/engine.py` | richer `MarkedItem`/`CorrectionReport`; `mark_scheme_files`; `MAX_FILES`; mark-scheme requirement; new error types; `get_engine()` dispatch |
| `backend/app/config.py` | `AIConfig`/`get_ai_config()`, guarded provider settings, version 6.2.0, phase 3 |
| `backend/app/api/system.py` | live engine state and feature flags (`ai_correction`/`grade_submission` from the engine; `pdf_processing` true) |
| `backend/app/api/__init__.py` | route-package description: no correction routes in Phase 3 |
| `backend/app/main.py` | application docstring: engine is idle until requested; no startup provider call |
| `backend/tests/test_engine.py` | updated contract/input-policy tests |
| `backend/tests/test_api_system.py` | Phase 3 status/flags/engine tests |
| `backend/tests/test_config.py` | provider-config tests |
| `backend/tests/conftest.py` | clears all `MC6_AI_*` variables |
| `backend/app/correction/documents.py` | completion-audit fix: preserve logical line breaks in extracted page text so scheme rows remain parseable |
| `backend/app/correction/scheme.py` | completion-audit fix: parse published `Question 1 (3 marks): …` rows and marks followed by a colon/text |
| `backend/tests/test_correction_scheme.py` | regression tests for the published scheme layout |
| `requirements.txt` | added `pypdf` |
| `.env.example` | documented provider variables |
| `main.py` | Phase 3 banner; honest no-key note |
| `frontend/js/pages/dashboard.js` | readiness reads the live engine flag |
| `frontend/js/pages/correction.js` | removed stale "engine not implemented" wording; Phase 4 explanation |
| `frontend/js/pages/settings.js` | provider configuration is server-side, not "planned" |
| `frontend/tests/pages.test.mjs` | updated phase wording + engine readiness test |
| `frontend/package.json` | version 6.2.0 |
| `README.md` | Phase 3 setup, engine, tests, limitations, roadmap |
| `docs/architecture.md` | engine architecture, module tree, dependency budget |
| `docs/correction-engine-contract.md` | rewritten to describe the implemented engine and the Phase 4 seam |
| `docs/phase-1-report.md` | roadmap note |

No files were removed.

## 4. Dependencies

| Dependency | Kind | Justification |
|---|---|---|
| `pypdf>=5,<7` | runtime | plain-Python PDF validation and page text extraction; no native build step. Installed and exercised in the test suite (6.21.1). |
| standard-library `urllib` | runtime | Gemini REST transport; avoids a provider SDK and its transitive dependency tree |

No new test dependency. Frontend runtime dependencies remain zero.

## 5. Tests executed and results

Commands:

```bash
PYTHONPATH=backend .venv/Scripts/python -m pytest backend/tests -q
cd frontend && npm test
```

| Suite | Result |
|---|---|
| Backend (pytest) | **167 passed**, exit 0, 1 pre-existing Starlette/httpx deprecation warning |
| Frontend (node --test) | **43 passed, 0 failed**, exit 0 |

Correction-specific coverage (87 tests):

- **Documents (14):** real multi-page PDF extraction, page numbers, missing,
  empty, oversized, mislabelled, unrecognisable, corrupt, zero-page,
  encrypted, textless PDF, an unreadable page, PNG/JPEG, role recording,
  byte reading.
- **Scheme (7):** labels/maxima, confident vs hint maxima, published
  `Question 1 (3 marks): …` rows over a real PDF, conflicts, missing
  structure, textless scheme, normalisation and natural sort.
- **Verification (8):** fractions/decimals/percentages/mixed numbers/units,
  algebraic equivalence, different variables → inconclusive, mark preservation,
  zero-with-correct-answer and full-marks-with-different-answer flags.
- **Validation (20):** totals/percentage, partial reports, missing questions,
  confident/weak maximum reconciliation, impossible and negative marks,
  duplicates, empty output, unreadable-with-mark, extra questions, sorting,
  over-counted criteria flagged without changing a mark, parent/subquestion
  coverage in both directions, a parent/subquestion maximum mismatch, and
  rejection of a parent plus child returned together (double counting).
- **Engine (17):** successful pipeline, ignored model totals, scheme file,
  provider failure, JSON repair (once only), invalid output rejection, corrupt
  PDF before provider call, partial report, request validation, not-found,
  caller files preserved, inline-budget fallback, untexted image failure,
  expected-total mismatch review, and log safety (no student content/paths).
- **Marking fixtures (12):** full credit, method-only credit, wrong final
  answer with method marks, arithmetic slip, alternative method,
  follow-through, confirmed blank, unreadable, ambiguous and missing answers,
  plus rejection above the maximum and preservation of feedback/criteria.
- **V5 reference fixture (1):** the authentic fixture PDFs are extracted and
  converted to a 4-question / 10-mark blueprint; the fixture's reference marks
  (3, 2, 2, 2) replay through validation to 9/10 and 90%.
- **Provider (8):** real HTTP request shape, inline PDF base64, retry on 503,
  429 exhaustion, auth failure without retry, truncation, blocked/empty
  responses, non-JSON body, and the **full engine over a real local HTTP
  provider stub**.

All existing Phase 1/2 tests still pass. No test was deleted, skipped or
weakened.

## 6. Marking evaluation

**No live-provider marking evaluation was performed.** No `MC6_AI_API_KEY`
was available in this environment, and the brief forbids spending paid/free
quota just to run routine tests.

What the automated tests establish:

- the pipeline invokes the real provider transport correctly;
- malformed, impossible and contradictory outputs are rejected or flagged;
- totals are consistent with accepted question marks;
- missing/unreadable questions never become silent zeros;
- failures produce failed jobs, not fabricated reports.

What they do **not** establish:

- accuracy on real Edexcel papers or student handwriting;
- that the model applies M/A/B/ECF/ISW correctly in every case;
- that the default model is available under a given key or region.

Synthetic marking fixtures exercise aggregation and validation around
representative decisions (full marks, method-only credit, wrong final answer,
missing answer, unreadable answer, ambiguity). They are not a substitute for
a real-world evaluation and are not reported as one.

### Bundled V5 reference fixture

V5 contained one authentic reference example: `data/fixtures/`
(`student_submission.pdf` and `mark_scheme.pdf`). It is a synthetic
Edexcel-style quiz with four questions worth 3 + 2 + 3 + 2 = 10 marks and
reference marks 3 + 2 + 2 + 2 = 9 (question 3 ends `n = 13.33` instead of
`14`). Both PDFs are now copied into `backend/tests/fixtures/v5/` and run
through the real extraction, blueprint and validation pipeline in
`test_v5_reference_fixture.py`.

This audit found and fixed two real defects that the previous tests missed:
PDF text was collapsed to one line per page (so only the first scheme row was
visible), and the blueprint did not recognise the published
`Question 1 (3 marks): …` layout. After the fixes the fixture yields questions
1–4 with maxima 3, 2, 3, 2, and the replayed reference marks produce 9/10
(90%, complete).

The reference marks are **replayed**, not generated by a model. This verifies
the integration and arithmetic on authentic fixture documents; it does not
measure live marking accuracy.

### Real V5 examination materials

The larger V5 materials were inspected without adding them to the repository.
`data/fixtures/real/Question paper.pdf` is a 16-page text PDF, but
`Student Answer.pdf` (15 pages, 5.5 MB) and `Answer Sheet.pdf` (26 pages,
8.5 MB) are image-only scans. Two representative `data/mark_schemes/*.pdf`
files (6.1 MB and 8.3 MB) are also image-only. A typical student-script plus
mark-scheme pair therefore exceeds the 12 MB inline provider budget; because
neither has extractable text, the engine fails honestly with a safe
"too large to send" message instead of marking from empty text. No live
marking run was attempted. Page rendering/compression for oversized scans is
not implemented in this phase (see §7).

## 7. Known limitations

1. **No live-provider evaluation or accuracy measurement** (see §6). This is
   the largest outstanding validation gap.
2. **No durable jobs and no HTTP correction routes.** Phase 3's `submit` is
   synchronous and its job registry is process-local; restart loses jobs. That
   is intentional scope, not an oversight.
3. **No browser upload or result display.** The correction page remains a
   draft UI and says so.
4. **M/A/B/ECF are model-interpreted.** There is no independent Python rule
   engine for method/accuracy/follow-through marks. Deterministic checks
   verify numeric/algebraic answer equivalence only.
5. **PDF text extraction is not OCR.** Scanned/handwritten pages depend on the
   provider's visual reading; textless pages are flagged.
6. **Inline payload ceiling (12 MB raw).** Very large uploads fall back to text;
   a textless document that cannot be sent fails. Images are sent as supplied
   (no downscaling/compression), and a Files-API upload path is not
   implemented. This matters for real V5 scans: its 5.5 MB student script and
   6–8 MB mark schemes are image-only, so a pair exceeds the budget and is
   rejected rather than marked.
7. **Mark-scheme blueprint extraction is heuristic.** It now recognises
   line-leading labels, `Question N (marks): …` rows and marks followed by a
   colon or question text, but it can still miss unusual layouts. It never
   blocks marking; unverified coverage is reported and sets `review_required`.
8. **No report files, grade boundaries or Classroom integration.**
9. **One provider family.** The client speaks the Gemini `generateContent`
   REST shape; it is not a generic OpenAI-compatible client.
10. **Concurrency is bounded per process (2), not globally.** Multi-process
    deployment would need its own limit.

## 8. Execution instructions

```bash
# install
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt

# run with correction enabled (server-side only)
MC6_AI_API_KEY=... .venv/Scripts/python main.py
# optional: MC6_AI_MODEL / MC6_AI_BASE_URL / MC6_AI_TIMEOUT_SECONDS / MC6_AI_MAX_RETRIES

# tests
PYTHONPATH=backend .venv/Scripts/python -m pytest backend/tests -q
cd frontend && npm test
```

Direct engine invocation:

```python
import asyncio
from app.engine import AssignmentContext, CorrectionOptions, CorrectionRequest, SubmissionFile, get_engine

engine = get_engine()
print(engine.describe())          # available/name/reason — no network call

request = CorrectionRequest(
    files=(SubmissionFile(path=..., filename="work.pdf",
                          media_type="application/pdf", size_bytes=...),),
    assignment=AssignmentContext(title="Algebra worksheet",
                                 mark_scheme="1(a)  2\n1(b)  1"),
    options=CorrectionOptions(),
    # mark_scheme_files=(...),    # optional instead of pasted text
)
job = asyncio.run(engine.submit(request))
if job.status.value == "completed":
    report = asyncio.run(engine.get_report(job.job_id))
```

## 9. Integration contract for Phase 4

- **Invocation:** construct `get_engine()` **once at startup** (e.g.
  `app.state.engine`) → `await submit(request)` → `await get_report(job_id)`.
  Depend on the protocol, never `CorrectionService`. The registry is per
  engine instance, so constructing it per request would lose jobs.
- **Input:** the frozen dataclasses in `engine.py`; paths stay server-side.
  A mark scheme is mandatory.
- **Output:** `CorrectionJob` (`job_id`, status, submitted_at, filenames,
  safe `error`) and `CorrectionReport` (items, totals, status, percentage,
  unresolved, review flags, warnings).
- **Failure:** policy violations raise `UnsupportedInputError`; an
  unconfigured engine raises `EngineUnavailableError`; document/provider/
  output failures return a `failed` job with a safe message; unknown ids raise
  `JobNotFoundError`; a report for a non-completed job raises `EngineError`.
- **Persistence:** Phase 4 must add migration `002` for jobs/items through
  `Storage`, persist a report before marking the job `completed`, and
  reconcile jobs left `processing` after a restart.
- **UI:** persist exactly the returned marks/totals; never recompute or invent
  question coverage in the browser.
- **Secrets:** the provider key stays server-side; `system/status` exposes only
  availability and a safe reason.

## 10. Definition of done (honest status)

| Requirement | Status |
|---|---|
| V5 correction pipeline inspected | Done |
| Existing V6 Phase 3 audit | Done — only the contract existed |
| Engine genuinely implemented | Done |
| Supported PDFs processed through the real pipeline | Done (pypdf; tests include real PDFs) |
| Questions/answers mapped with explicit uncertainty | Done for schema/statuses; mapping is model-driven |
| Mark schemes interpreted and applied | Done via the model + blueprint; heuristic limits documented |
| M/A/B and follow-through handled | Prompt-level only; no independent rule engine |
| Mathematical verification implemented where appropriate | Done for numeric/algebraic equivalence, never changing marks |
| Every accepted mark validated against its maximum | Done; violations reject the result |
| Totals and percentages consistent | Done, recomputed; partial results have no percentage |
| Incomplete/ambiguous results represented honestly | Done |
| Provider failures/malformed responses handled | Done |
| Deterministic tests cover principal rules | Done for pipeline/validation; model marking is not deterministic |
| Regression tests pass | Done — 165 backend, 43 frontend |
| Real-world examples evaluated | **Partial** — bundled V5 fixture runs end to end with reference marks replayed; real V5 scans were inspected but are textless and too large as a pair; no live-model run |
| Output schema/interface documented for Phase 4 | Done |
| No unrelated features added | Done |

## 11. Roadmap

| Phase | Status |
|---|---|
| 1 — Interface foundation | Complete |
| 2 — Backend foundation | Complete |
| 3 — Mathematical correction engine | Complete (live-accuracy evaluation deferred) |
| 4 — Application integration | Not started: upload endpoints, durable jobs, results UI, reports |
| Later — Classroom sync, rosters, deployment hardening | Deferred |
