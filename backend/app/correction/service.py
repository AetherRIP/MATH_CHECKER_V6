"""Orchestration of one correction: documents → provider → validation.

The service implements the :class:`app.engine.CorrectionEngine` protocol. It
owns the sequence, not the rules:

1. validate the request through the contract's single input-policy owner;
2. validate and extract every document;
3. extract a conservative mark-scheme blueprint;
4. build the provider request (documents inline, extracted text as context);
5. parse and validate the response, with one bounded JSON-repair attempt;
6. run deterministic answer checks (which never change a mark);
7. return a completed job/report, or a failed job with a safe message.

Phase 3 processes synchronously. The job/report registry is process-local and
exists so the protocol's lookup methods are usable; durable job persistence
and the ``queued``/``processing`` lifecycle are Phase 4 work and are not
implemented here.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import replace
from typing import Callable

from ..config import ConfigError, get_ai_config
from ..engine import (
    CorrectionEngine,
    CorrectionJob,
    CorrectionReport,
    CorrectionRequest,
    EngineError,
    EngineInfo,
    ExtractionError,
    InvalidEngineOutput,
    JobNotFoundError,
    JobStatus,
    ProviderError,
    UnavailableEngine,
    UnsupportedInputError,
    validate_request,
)
from ..models import new_id, utc_now
from .documents import ExtractedDocument, extract_document, read_document_bytes
from .parsing import parse_json_object
from .prompts import SYSTEM_PROMPT, build_repair_prompt, build_user_prompt
from .provider import GeminiClient, MAX_INLINE_BYTES, ModelAttachment, ModelClient, ModelRequest
from .scheme import build_blueprint
from .validation import validate_model_output
from .verify import verify_items

log = logging.getLogger("mathchecker.correction.service")

_GENERIC_FAILURE = "The correction engine failed unexpectedly. The job was not completed."
_EXTRACTION_FAILURE = "The submitted documents could not be processed."
_NOT_COMPLETED = "The correction has not completed, so no report is available."

# The Phase 3 registry is process-local, so it must not grow without bound.
# Phase 4 replaces it with durable storage.
_MAX_REMEMBERED_JOBS = 50


def create_engine() -> CorrectionEngine:
    """Build the engine from server configuration.

    Returns :class:`UnavailableEngine` (with a safe reason) when no key is set
    or the optional provider configuration is invalid. This is the only place
    that reads provider configuration for correction.
    """
    try:
        config = get_ai_config()
    except ConfigError as exc:
        # The config error names a variable, never its value. The public reason
        # stays generic; operators get the actionable detail in the log.
        log.error("AI provider configuration is invalid: %s", exc)
        return UnavailableEngine(
            "The AI provider configuration is invalid. Check the server's AI settings."
        )
    if config is None:
        return UnavailableEngine()

    try:
        client = GeminiClient(
            api_key=config.api_key,
            model=config.model,
            base_url=config.base_url,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
        )
    except ValueError:
        return UnavailableEngine("The AI provider is not configured correctly.")

    return CorrectionService(client=client)


class CorrectionService:
    """The Phase 3 correction engine."""

    def __init__(
        self,
        *,
        client: ModelClient,
        extract: Callable[[object, str], ExtractedDocument] = extract_document,
        clock: Callable[[], str] = utc_now,
        max_inline_bytes: int = MAX_INLINE_BYTES,
    ):
        self._client = client
        self._extract = extract
        self._clock = clock
        self._max_inline_bytes = max_inline_bytes
        # Bounds concurrent provider calls in this process. Phase 4 may run
        # several jobs; this keeps a free-tier key from being hammered.
        self._provider_slots = threading.BoundedSemaphore(2)
        self._jobs: dict[str, CorrectionJob] = {}
        self._reports: dict[str, CorrectionReport] = {}

    # --- protocol ---------------------------------------------------------

    def describe(self) -> EngineInfo:
        return EngineInfo(name=self._client.name, available=True)

    async def submit(self, request: CorrectionRequest) -> CorrectionJob:
        validate_request(request)

        job_id = request.job_id or new_id()
        submitted_at = self._clock()
        filenames = tuple(
            [item.filename for item in request.files]
            + [item.filename for item in request.mark_scheme_files]
        )
        started = time.perf_counter()

        try:
            # The pipeline performs blocking file and network I/O. Running it
            # in a worker thread keeps an async caller's event loop responsive
            # and lets Phase 4 run jobs without blocking request handling.
            report = await asyncio.to_thread(
                self._run, request, job_id=job_id, created_at=submitted_at
            )
        except UnsupportedInputError:
            raise
        except (ExtractionError, ProviderError, InvalidEngineOutput) as exc:
            job = CorrectionJob(
                job_id=job_id,
                status=JobStatus.FAILED,
                submitted_at=submitted_at,
                files=filenames,
                error=str(exc) or _EXTRACTION_FAILURE,
            )
            log.warning(
                "correction job %s failed after %.1fs (%s)",
                job_id,
                time.perf_counter() - started,
                type(exc).__name__,
            )
            self._remember(job)
            return job
        except Exception:
            log.exception("correction job %s crashed", job_id)
            job = CorrectionJob(
                job_id=job_id,
                status=JobStatus.FAILED,
                submitted_at=submitted_at,
                files=filenames,
                error=_GENERIC_FAILURE,
            )
            self._remember(job)
            return job

        job = CorrectionJob(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            submitted_at=submitted_at,
            files=filenames,
        )
        self._remember(job, report)
        log.info(
            "correction job %s completed in %.1fs (%d questions, %.2f/%.2f)",
            job_id,
            time.perf_counter() - started,
            len(report.items),
            report.awarded if report.awarded is not None else -1,
            report.out_of if report.out_of is not None else -1,
        )
        return job

    def _remember(
        self, job: CorrectionJob, report: CorrectionReport | None = None
    ) -> None:
        """Store one result, keeping the process-local registry bounded."""
        self._jobs[job.job_id] = job
        if report is not None:
            self._reports[job.job_id] = report
        while len(self._jobs) > _MAX_REMEMBERED_JOBS:
            oldest = next(iter(self._jobs))
            self._jobs.pop(oldest, None)
            self._reports.pop(oldest, None)

    async def get_job(self, job_id: str) -> CorrectionJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError("The requested correction job was not found.")
        return job

    async def get_report(self, job_id: str) -> CorrectionReport:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError("The requested correction job was not found.")
        report = self._reports.get(job_id)
        if job.status is not JobStatus.COMPLETED or report is None:
            raise EngineError(_NOT_COMPLETED)
        return report

    # --- pipeline ---------------------------------------------------------

    def _run(
        self, request: CorrectionRequest, *, job_id: str, created_at: str
    ) -> CorrectionReport:
        submission_documents = [
            self._extract(item, "submission") for item in request.files
        ]
        scheme_documents = [
            self._extract(item, "mark_scheme") for item in request.mark_scheme_files
        ]

        warnings: list[str] = []
        for document in (*submission_documents, *scheme_documents):
            warnings.extend(document.warnings)

        blueprint = build_blueprint(
            scheme_documents, extra_text=request.assignment.mark_scheme
        )
        prompt = build_user_prompt(
            assignment=request.assignment,
            options=request.options,
            blueprint=blueprint,
            submission_documents=submission_documents,
            scheme_documents=scheme_documents,
        )

        attachments, attachment_warnings = self._select_attachments(
            submission_documents, scheme_documents
        )
        warnings.extend(attachment_warnings)

        with self._provider_slots:
            raw = self._client.generate(
                ModelRequest(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=prompt,
                    attachments=attachments,
                )
            )

        try:
            payload = parse_json_object(raw)
        except InvalidEngineOutput:
            # One bounded repair attempt. The repair request carries no
            # documents: it only asks for valid JSON of the decisions already
            # made, so it cannot consume the provider's document budget twice.
            log.info("correction job %s returned invalid JSON; attempting one repair", job_id)
            with self._provider_slots:
                repaired = self._client.generate(
                    ModelRequest(
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=build_repair_prompt(raw),
                    )
                )
            payload = parse_json_object(repaired)

        report = validate_model_output(
            payload,
            blueprint=blueprint,
            job_id=job_id,
            engine_name=self._client.name,
            created_at=created_at,
        )

        verified_items, verification_warnings = verify_items(report.items)
        all_warnings = (*report.warnings, *warnings, *verification_warnings)
        review_required = report.review_required or any(
            item.review_flags for item in verified_items
        )

        expected_total = request.options.max_score
        if (
            expected_total is not None
            and report.out_of is not None
            and abs(expected_total - report.out_of) > 1e-9
        ):
            all_warnings = (
                *all_warnings,
                f"The marked total available ({report.out_of:g}) differs from the "
                f"expected total ({expected_total:g}); review the question coverage.",
            )
            review_required = True

        return replace(
            report,
            items=verified_items,
            warnings=all_warnings,
            review_required=review_required,
        )

    def _select_attachments(
        self,
        submission_documents: list[ExtractedDocument],
        scheme_documents: list[ExtractedDocument],
    ) -> tuple[tuple[ModelAttachment, ...], list[str]]:
        """Choose documents to send inline, respecting the provider's bound.

        Submission pages are sent first because they contain the handwriting
        and diagrams that text extraction cannot capture. A document with no
        extractable text that cannot be sent visually makes the request
        unmarkable and fails honestly.
        """
        warnings: list[str] = []
        chosen: list[ModelAttachment] = []
        used = 0

        for document in (*submission_documents, *scheme_documents):
            data = read_document_bytes(document)
            if used + len(data) <= self._max_inline_bytes:
                chosen.append(
                    ModelAttachment(
                        filename=document.filename,
                        media_type=document.media_type,
                        data=data,
                    )
                )
                used += len(data)
                continue

            if not document.has_text:
                raise ExtractionError(
                    f"'{document.filename}' has no extractable text and is too large "
                    "to send to the AI provider. Reduce its size and try again."
                )
            warnings.append(
                f"'{document.filename}' was not sent visually because the uploads exceed "
                "the provider's inline size limit; only its extracted text was used."
            )

        return tuple(chosen), warnings


__all__ = ["CorrectionService", "create_engine", "CorrectionEngine"]
