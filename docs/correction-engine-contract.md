# Correction-engine contract (Phase 3)

**Status: implemented.** The engine lives in `backend/app/correction/` and is
reachable through `backend/app/engine.py`'s `CorrectionEngine` protocol and
`get_engine()` construction point.

Phase 3 delivers the correction component only. It does **not** add the
durable correction-job lifecycle, upload endpoints, or frontend wiring; those
are Phase 4 work against the same interface.

---

## 1. Public interface

`backend/app/engine.py` is the fixed seam:

| Method | Kind | Contract |
|---|---|---|
| `describe() -> EngineInfo` | sync, cheap | `name`, `available`, and a user-safe `reason` when unavailable. No network call. |
| `submit(request) -> CorrectionJob` | async | Validates the request, runs one correction synchronously in a worker thread, and returns a `completed` or `failed` job. Raises `UnsupportedInputError` for policy violations and `EngineUnavailableError` when no provider is configured. |
| `get_job(job_id) -> CorrectionJob` | async | Process-local lookup. Raises `JobNotFoundError` for an unknown id. |
| `get_report(job_id) -> CorrectionReport` | async | Report for a completed job. Raises `JobNotFoundError` or `EngineError` if the run failed/never completed. |

`get_engine()` is the only construction point. It returns the Gemini-backed
`CorrectionService` when `MC6_AI_API_KEY` is set and valid, otherwise an
`UnavailableEngine` whose `describe().reason` explains that correction is
unavailable. A configured engine is constructed without contacting the
provider.

### Phase 3 vs Phase 4 lifecycle

Phase 3 runs one correction per `submit()` call and reports the terminal
`completed` / `failed` state. `queued` and `processing` are defined in
`JobStatus` for the durable lifecycle but are not produced here. The job and
report registries are process-local and are lost on restart by design — Phase
4 owns persistence and the `queued → processing → completed | failed`
transitions.

## 2. Input contract

`CorrectionRequest` (frozen dataclasses in `engine.py`):

| Type | Fields |
|---|---|
| `SubmissionFile` | `path` (server-only), `filename`, `media_type`, `size_bytes` |
| `AssignmentContext` | `title`, `instructions`, `mark_scheme` (pasted text) |
| `CorrectionOptions` | `partial_credit`, `max_score`, `feedback_detail` |
| `CorrectionRequest` | `files`, `assignment`, `options`, `mark_scheme_files` (added in Phase 3) |

`validate_request()` is the single input-policy owner:

- at least one student file;
- a non-empty assignment title;
- **a mark scheme is mandatory** — one or more `mark_scheme_files`, non-empty
  `assignment.mark_scheme` text, or both;
- accepted media types: `application/pdf`, `image/png`, `image/jpeg`;
- per-file size limit: 25 MB (`MAX_FILE_BYTES`);
- at most 12 files in total (`MAX_FILES`);
- every metadata size must be positive.

The browser enforces the same types/size before upload; the backend check is
authoritative. Shapes never include server paths.

### Document handling

`backend/app/correction/documents.py` validates bytes, not filenames:

- the file must exist, be non-empty, and match its declared media type by
  magic bytes;
- PDFs must open, must not be password-protected, must have 1–200 pages, and
  are read with `pypdf`; text is kept per page and page numbers are preserved.
  Logical line breaks are preserved so question rows stay parseable; spaces
  within a line are normalised;
- a page with no extractable text is recorded as such (it is not treated as a
  blank answer); the document is still sent visually if it fits;
- corrupt/encrypted/oversized/mislabelled files raise `ExtractionError` with a
  user-safe message;
- text extraction is bounded (60,000 characters per document, 12,000 per page)
  and truncation is reported;
- PDFs and images are sent inline to the provider (12 MB of raw bytes, about
  16 MB after base64 encoding) for
  visual interpretation of handwriting and diagrams. Documents beyond that
  budget contribute extracted text only, with a warning; a document with no
  text that cannot be sent fails honestly.

The engine creates no temporary files and never deletes a caller-owned file.
Phase 4 owns the upload workspace and its cleanup.

## 3. Output schema

`MarkedItem` — one question/subquestion:

| Field | Meaning |
|---|---|
| `label` | normalised question label (`1(a)`, `1(b)(ii)`) |
| `awarded` | numeric mark, or `null` when not determinable. **Zero is a real mark.** |
| `out_of` | maximum from the scheme, or `null` when unknown |
| `feedback` | precise explanation of marks awarded/lost |
| `criteria` | mark-scheme criteria applied (`M1`, `A1`, …) with awarded/not and reason |
| `student_evidence`, `scheme_evidence` | visible working and the rule applied |
| `student_answer`, `scheme_answer` | short values used for the deterministic check |
| `verification` | outcome of the deterministic check, or why none was possible |
| `status` | `marked`, `unresolved`, `unreadable`, `missing`, `ambiguous` |
| `warnings` | question-level extraction/interpretation notes |
| `review_flags` | explicit uncertainty categories (no numeric confidence) |

Review flag vocabulary: `answer_extraction_uncertain`,
`question_mapping_uncertain`, `mark_scheme_ambiguous`,
`mark_scheme_incomplete`, `verification_inconclusive`,
`mark_allocation_review`, `diagram_not_assessable`,
`multiple_possible_readings`, `scheme_disagreement`.

`CorrectionReport` — the whole job:

| Field | Meaning |
|---|---|
| `job_id`, `created_at`, `engine` | identity and provenance |
| `summary` | model summary (may be empty; never fabricated) |
| `items` | question results in natural label order |
| `awarded` | sum of accepted question marks, or `null` when none were accepted |
| `out_of` | sum of maxima only when every maximum is known, else `null` |
| `status` | `completed` or `partial` |
| `percentage` | `awarded / out_of × 100`, only for a complete report with `out_of > 0` |
| `unresolved` | labels whose status is not `marked` |
| `review_required` | true when any review flag, unresolved question, unverified coverage, or deterministic conflict exists |
| `warnings` | extraction, mapping, maximum, verification and coverage notes |

A job is **complete** only when every item is `marked`, every item has a mark
and a maximum, and no question from the extracted blueprint is missing. A
partial report has no percentage. Its `awarded` is the sum of accepted marks
and must not be presented as a final score.

A `completed` **job** can carry a `partial` **report**: the run finished, but
some questions need review or could not be read. Phase 4 must keep those two
states distinct rather than treating a partial report as a failed job or as a
finished grade.

## 4. Pipeline

```
validate_request
      │
      ▼
documents.extract_document × N         validate bytes, extract text/pages
      │
      ▼
scheme.build_blueprint                 conservative labels + maxima
      │
      ▼
prompts.build_user_prompt              rules, scheme, extracted text, blueprint
      │
      ▼
provider.GeminiClient.generate         documents inline + JSON response
      │
      ▼
parsing.parse_json_object              strict JSON (one repair attempt)
      │
      ▼
validation.validate_model_output       marks, maxima, coverage, totals
      │
      ▼
verify.verify_items                    deterministic checks (never changes marks)
      │
      ▼
CorrectionReport + CorrectionJob
```

Modules:

| Module | Responsibility |
|---|---|
| `documents.py` | byte-level validation, PDF/image extraction, page context |
| `scheme.py` | conservative mark-scheme question/maximum extraction |
| `prompts.py` | system/user prompts and the required JSON shape |
| `provider.py` | `ModelClient` protocol + Gemini REST client, bounded retries |
| `parsing.py` | code-fence/stray-text tolerant JSON object parsing |
| `validation.py` | schema/marking-rule validation, maxima, totals, completeness |
| `verify.py` | numeric/fraction/percentage/expression equivalence checks |
| `service.py` | orchestration, provider wiring, process-local job registry |

## 5. Provider configuration

Environment (`MC6_*`, server-side only):

| Variable | Default | Purpose |
|---|---|---|
| `MC6_AI_API_KEY` | — | enables the engine (required) |
| `MC6_AI_MODEL` | `gemini-2.5-flash` | model name |
| `MC6_AI_BASE_URL` | `https://generativelanguage.googleapis.com` | endpoint |
| `MC6_AI_TIMEOUT_SECONDS` | `180` | per-request timeout (5–600) |
| `MC6_AI_MAX_RETRIES` | `2` | transient retries (0–5) |

The key is sent in the `x-goog-api-key` header and is never returned, logged,
stored in the browser, or included in an error message. Provider failures map
to safe messages: rejected key, rate limit, unavailable service, timeout,
blocked prompt, truncated/empty response. Retries are bounded and only apply
to timeouts, 429 and 5xx; the JSON-repair attempt is a single extra call with
no documents attached.

Provider concurrency is bounded to two in-process calls. Phase 4 remains
responsible for choosing how many jobs run at once.

## 6. What is deterministic, and what is not

Deterministic (pure Python):

- input and byte-level document validation;
- PDF page/text extraction and truncation reporting;
- blueprint labels/maxima and conflict detection, including line-leading
  `1(a) 2`, bracket/parenthesised maxima, and published
  `Question 1 (3 marks): …` rows;
- JSON schema and mark-range validation (`0 ≤ awarded ≤ out_of`);
- maximum reconciliation with an unambiguous scheme value;
- coverage reconciliation (missing questions become unresolved, not zero);
- parent/subquestion coverage: returning `1(a)`, `1(b)` for a scheme row `1`
  is accepted, but their maxima must add up to the parent total; a mismatch
  makes the report partial;
- double counting is rejected: returning both `1` and `1(a)` fails the job
  rather than adding the same marks twice;
- totals and percentage (never taken from the model);
- numeric answer equivalence (`3/4`, `0.75`, `75%`, `1 1/2`, units);
- algebraic equivalence by numeric sampling for simple expressions;
- review flags when a deterministic answer check contradicts the award.

Not deterministic / not verified:

- method, accuracy and follow-through judgements are made by the model from
  the mark scheme; there is no independent M/A/B rule engine;
- handwriting, diagrams and scans depend on the provider's visual reading;
- a syntactically valid response is not proof that the marking is correct;
- mark-scheme blueprint extraction is heuristic (it never blocks marking, and
  unverified coverage is reported);
- no live provider run was possible in this repository without an API key, so
  no real-world accuracy claim is made. The bundled V5 fixture is replayed
  through the real pipeline with its reference marks; that verifies document
  handling and arithmetic, not model accuracy.

## 7. HTTP surface (Phase 4, not implemented in Phase 3)

| Endpoint | Purpose | Success | Notable failures |
|---|---|---|---|
| `POST /api/corrections` | multipart submit | `202` + `CorrectionJob` | `422 unsupported_input`, `503 engine_unavailable` |
| `GET /api/corrections` | recent jobs | `200` + `{jobs: [...]}` | — |
| `GET /api/corrections/{job_id}` | job state | `200` + `CorrectionJob` | `404 job_not_found` |
| `GET /api/corrections/{job_id}/report` | report | `200` + `CorrectionReport` | `404 job_not_found`, `409 report_not_ready` |

All errors use the existing envelope. This table is the Phase 4 target, not a
description of routes that exist today.

## 8. Integrating in Phase 4

```python
from app.engine import CorrectionRequest, get_engine

# Construct ONCE at application startup and keep the instance (for example on
# app.state): the job registry is per engine instance. Calling get_engine()
# per request would create a fresh registry and lose earlier jobs.
engine = get_engine()
if not engine.describe().available:
    ...  # show describe().reason; do not offer Start

job = await engine.submit(request)          # completed or failed job
if job.status is JobStatus.COMPLETED:
    report = await engine.get_report(job.job_id)
```

Phase 4 responsibilities:

1. persist jobs, input references and the report (new migration through the
   existing storage boundary);
2. run `submit` in a background task/thread and persist `queued`/`processing`
   transitions; reconcile orphaned jobs after a restart;
3. persist per-question `MarkedItem` rows and report-level totals exactly as
   returned (no recalculation in the UI);
4. add the HTTP routes above, mapping `EngineError` subclasses to the error
   codes in §7;
5. wire the correction page and Task Manager to the real API;
6. generate reports from persisted results only, and flip the `reports` flag
   only when that works end to end.

## 9. Non-goals of this contract

Google Classroom sync, rosters/classes, multi-account infrastructure,
distributed workers, a second persistence or configuration system, report
file formats, grade boundaries, and a full UI redesign.
