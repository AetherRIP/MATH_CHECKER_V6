"""Classroom integration service for Math Checker V6.

Migrated from V5's ``sync.py`` + ``managed.py`` + ``report_attachment.py``
orchestration, adapted to V6's :class:`~app.storage.Storage` boundary and
:class:`~app.correction.jobs.CorrectionJobService`:

* courses / coursework / submissions are cached in SQLite keyed by Google's
  stable ids (never names);
* ``managed`` membership is persisted when THIS app creates the coursework and
  is never inferred from anything else;
* every grade / attachment / return operation is recorded in
  ``classroom_publish_ops`` with the REAL Google outcome — pending, refused,
  failed, not-supported and published are distinct states;
* a re-correction of the same submission UPDATES the one canonical Drive file
  in place (Classroom has no removeAttachments), preventing duplicate reports;
* report upload success is verified by re-reading the submission; a 200 from
  ``modifyAttachments`` alone is not treated as proof.

Student data safety: only stable ids, state and grade fields are persisted;
attachment contents flow through the correction engine without being logged.
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass

from ..db import CURRENT_SCHEMA_VERSION
from ..engine import JobStatus
from . import auth as classroom_auth
from . import client as gc
from .client import ClassroomApiError, ClassroomClient

log = logging.getLogger("mathchecker.classroom.service")

DEFAULT_TTL_SECONDS = 15 * 60
# Report filename carries the student and assignment, sanitised for all
# targets (Windows + POSIX + Drive).
_FILENAME_ILLEGAL = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_MAX_STEM = 120


def sanitize_component(value: str | None, *, fallback: str = "report") -> str:
    text = unicodedata.normalize("NFC", str(value or "")).strip()
    text = _FILENAME_ILLEGAL.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("..", " ").lstrip(".- ").strip()
    if len(text) > _MAX_STEM:
        text = text[:_MAX_STEM].rstrip(" .-")
    return text or fallback


def build_report_filename(student_name: str | None, assignment_title: str | None) -> str:
    """``Student_Assignment_Correction_Report.pdf`` — deterministic, safe."""
    student = sanitize_component(student_name, fallback="Student")
    assignment = sanitize_component(assignment_title, fallback="Assignment")
    return f"{student}_{assignment}_Correction_Report.pdf"


@dataclass(frozen=True)
class PublishOp:
    id: str
    coursework_id: str
    submission_id: str
    op_type: str
    status: str
    message: str | None
    drive_file_id: str | None
    job_id: str | None


#: Publication status values, shared with the API surface.
STATUS_PENDING = "pending"
STATUS_PUBLISHED = "published"
STATUS_FAILED = "failed"
STATUS_NOT_SUPPORTED = "not_supported"
STATUS_REQUIRES_AUTH = "requires_auth"
STATUS_SKIPPED = "skipped"
STATUS_REFUSED = "refused"


class ClassroomService:
    """Owns the Google-facing workflow on top of V6 storage."""

    def __init__(self, storage, *, client: ClassroomClient | None = None,
                 publish_allowed: bool = True, clock=time.time):
        self.storage = storage
        self.client = client or ClassroomClient(publish_allowed=publish_allowed)
        self.publish_allowed = publish_allowed
        self._clock = clock

    # ------------------------------------------------------------------ auth

    def auth_state(self, *, email: str | None = None) -> dict:
        return classroom_auth.auth_state(connected=email is not None or None, email=email)

    def connect(self, *, redirect_fn=None, open_browser: bool = True) -> dict:
        return classroom_auth.start_connect_flow(
            redirect_fn=redirect_fn, open_browser=open_browser)

    def disconnect(self) -> dict:
        classroom_auth.disconnect()
        return {"connected": False}

    def _token(self) -> str:
        return classroom_auth.get_access_token()

    # ------------------------------------------------------------------ sync

    def sync_courses(self, *, force: bool = False) -> list[dict]:
        now = self._clock()
        cached = self.storage.classroom_courses_fresh(now - DEFAULT_TTL_SECONDS)
        if cached and not force:
            return cached
        token = self._token()
        courses = self.client.list_teacher_courses(token)
        self.storage.classroom_replace_courses(courses, fetched_at=now)
        return self.storage.classroom_courses_fresh(0.0)

    def sync_coursework(self, course_id: str, *, force: bool = False) -> list[dict]:
        now = self._clock()
        if not force and self.storage.classroom_coursework_fresh(course_id, now - DEFAULT_TTL_SECONDS):
            return self.storage.classroom_coursework_rows(course_id)
        token = self._token()
        # Coursework rows reference their course; cache the parent first so
        # a direct coursework sync cannot violate the foreign key.
        if not self.storage.classroom_course_cached(course_id):
            courses = self.client.list_teacher_courses(token)
            self.storage.classroom_replace_courses(courses, fetched_at=now)
        items = self.client.list_assignments(token, course_id)
        self.storage.classroom_replace_coursework(
            course_id, items, fetched_at=now,
            live_ids={str(item.get("id")) for item in items},
        )
        return self.storage.classroom_coursework_rows(course_id)

    def sync_submissions(self, course_id: str, coursework_id: str, *,
                         force: bool = False) -> list[dict]:
        now = self._clock()
        if not force and self.storage.classroom_submissions_fresh(
                coursework_id, now - DEFAULT_TTL_SECONDS):
            return self.storage.classroom_submission_rows(coursework_id)
        token = self._token()
        roster = {
            student.get("userId"): student.get("profile") or {}
            for student in self.client.list_course_students(token, course_id)
        }
        submissions = self.client.list_student_submissions(token, course_id, coursework_id)
        self.storage.classroom_replace_submissions(
            coursework_id, submissions, roster=roster, now_ts=now)
        return self.storage.classroom_submission_rows(coursework_id)

    def link_correction(self, coursework_id: str, submission_id: str,
                        job_id: str) -> None:
        """Associate a durable correction job with a Classroom submission."""
        self.storage.classroom_link_job(submission_id, job_id)

    # ------------------------------------------------------------- write-back

    def _record_op(self, *, coursework_id: str, submission_id: str,
                   op_type: str, payload: dict, student_id: str | None,
                   job_id: str | None = None) -> str:
        return self.storage.classroom_insert_publish_op(
            coursework_id=coursework_id,
            submission_id=submission_id,
            op_type=op_type,
            payload=json.dumps(payload, default=str),
            student_id=student_id,
            job_id=job_id,
            now_iso=_iso_now(),
            status=STATUS_PENDING,
        )

    def _finish_op(self, op_id: str, *, status: str, message: str | None = None,
                   http_status: int | None = None, error_code: str | None = None,
                   drive_file_id: str | None = None) -> PublishOp:
        row = self.storage.classroom_finish_publish_op(
            op_id, status=status, message=message, http_status=http_status,
            error_code=error_code, drive_file_id=drive_file_id,
            finished_at=_iso_now(),
        )
        return PublishOp(
            id=row["id"], coursework_id=row["coursework_id"],
            submission_id=row["submission_id"], op_type=row["op_type"],
            status=row["status"], message=row["message"],
            drive_file_id=row["drive_file_id"], job_id=row["result_job_id"],
        )

    @staticmethod
    def translate_error(exc: ClassroomApiError) -> dict:
        """Translate a ClassroomApiError honestly (V5-managed parity)."""
        status = exc.status
        detail = exc.detail or ""
        if status == 401:
            return {"status": STATUS_REQUIRES_AUTH, "http": 401, "code": None,
                    "message": "Google authorization expired. Reconnect Google Classroom."}
        if status == 403:
            if ("Publishing is disabled" in detail
                    or "PERMISSION_DENIED" in detail
                    or "ProjectPermissionDenied" in detail
                    or "forbidden" in detail.lower()):
                return {"status": STATUS_NOT_SUPPORTED, "http": 403,
                        "code": "permission_denied",
                        "message": detail or (
                            "Google Classroom refused the operation: only the "
                            "integration that created this assignment may change "
                            "its grades or attachments.")}
            return {"status": STATUS_FAILED, "http": 403, "code": "forbidden",
                    "message": detail or "Google refused the operation (403)."}
        if status == 404:
            return {"status": STATUS_FAILED, "http": 404, "code": "not_found",
                    "message": "Google could not find that submission. Re-sync and retry."}
        if status == 429:
            return {"status": STATUS_FAILED, "http": 429, "code": "rate_limited",
                    "message": "Google rate-limited the request. Try again shortly."}
        if status >= 500:
            return {"status": STATUS_FAILED, "http": status, "code": "google_error",
                    "message": f"Google reported a server error ({status}). Try again shortly."}
        return {"status": STATUS_FAILED, "http": status, "code": None,
                "message": detail or "The Google API call failed."}

    def publish_grade(self, coursework_id: str, submission_id: str, *,
                      grade: float, return_to_student: bool,
                      assigned: bool, student_id: str | None = None,
                      job_id: str | None = None) -> PublishOp:
        """Write a grade (and optionally return the submission) with truth.

        ``assigned`` also writes ``assignedGrade`` — Google requires the draft
        to be present whenever an assigned grade is written, and the ``return``
        call does not copy the draft, so both happen together.
        """
        op_id = self._record_op(
            coursework_id=coursework_id, submission_id=submission_id,
            op_type="return" if return_to_student else
                    ("assign_grade" if assigned else "draft_grade"),
            payload={"grade": grade, "assigned": assigned, },
            student_id=student_id, job_id=job_id,
        )
        token = self._safe_token()
        if token is None:
            return self._finish_op(op_id, status=STATUS_REQUIRES_AUTH,
                                   message=classroom_auth.AuthError(
                                       "not connected").args[0])
        course_id = self._course_of(coursework_id, submission_id)
        if course_id is None:
            return self._finish_op(
                op_id, status=STATUS_FAILED,
                message=("This Classroom submission's course is not cached. "
                         "Sync the course and assignment again, then retry."),
                error_code="course_unresolved")
        try:
            self.client.patch_grade_fields(
                token, course_id, coursework_id, submission_id,
                grade=grade, assigned=assigned)
            if return_to_student:
                returned = self.client.return_submission(
                    token, course_id, coursework_id, submission_id)
                # Record the state change locally so the cache shows the
                # submission as returned even before the next sync.
                new_state = str(returned.get("state") or "")
                if new_state and new_state != "TURNED_IN":
                    self.storage.classroom_replace_submissions(
                        coursework_id, [returned], roster={},
                        now_ts=time.time())
        except ClassroomApiError as exc:
            translated = self.translate_error(exc)
            return self._finish_op(
                op_id, status=translated["status"],
                message=translated["message"],
                http_status=translated["http"], error_code=translated["code"])
        except Exception as exc:  # noqa: BLE001 — honest failure, never hidden
            return self._finish_op(op_id, status=STATUS_FAILED,
                                   message=str(exc)[:500])
        message = (
            f"Final grade {grade:g} assigned and returned to the student."
            if return_to_student and assigned else
            f"Final grade {grade:g} assigned to the submission."
            if assigned else
            f"Draft grade {grade:g} saved (not yet visible to the student)."
        )
        return self._finish_op(op_id, status=STATUS_PUBLISHED, message=message)

    def attach_report(self, coursework_id: str, submission_id: str, *,
                      pdf_bytes: bytes, filename: str, student_id: str | None,
                      job_id: str | None = None) -> PublishOp:
        """Upload the report to Drive and attach it to ONE student submission.

        * refuses to attach when the app did not create the coursework
          (``associatedWithDeveloper``) — before spending an upload;
        * one canonical report per submission: a re-correction PATCHes the
          existing Drive file in place instead of adding a second one;
        * success is VERIFIED by re-reading the submission and Drive.
        """
        op_id = self._record_op(
            coursework_id=coursework_id, submission_id=submission_id,
            op_type="attach_report", payload={"filename": filename},
            student_id=student_id, job_id=job_id,
        )
        token = self._safe_token()
        if token is None:
            return self._finish_op(op_id, status=STATUS_REQUIRES_AUTH,
                                   message="Google Classroom is not connected.")
        course_id = self._course_of(coursework_id, submission_id)
        if course_id is None:
            return self._finish_op(
                op_id, status=STATUS_FAILED,
                message=("This Classroom submission's course is not cached. "
                         "Sync the course and assignment again, then retry."),
                error_code="course_unresolved")
        try:
            current = self.client.get_student_submission(
                token, course_id, coursework_id, submission_id)
        except ClassroomApiError as exc:
            translated = self.translate_error(exc)
            return self._finish_op(op_id, status=translated["status"],
                                   message=translated["message"],
                                   http_status=translated["http"],
                                   error_code=translated["code"])

        if not gc.submission_can_be_modified(current):
            return self._finish_op(
                op_id, status=STATUS_NOT_SUPPORTED,
                message=("Google only lets this app modify submissions for "
                         "assignments the app itself created. Attach the report "
                         "from the Classroom UI for this assignment."),
                error_code="not_modifiable")

        canonical = self.storage.classroom_canonical_report(submission_id)
        existing_ids = set(gc.drive_attachment_ids(current))
        prior_file_id = None
        if canonical and canonical.get("drive_file_id") in existing_ids:
            prior_file_id = canonical["drive_file_id"]

        try:
            if prior_file_id:
                # Replace in place; Classroom has no removeAttachments, so
                # adding another file would create a duplicate report.
                self.client.replace_drive_file_content(token, prior_file_id, pdf_bytes)
                drive_file_id = prior_file_id
            else:
                temp_token = f"mc6-{int(self._clock())}"
                uploaded = self.client.upload_report_to_drive(
                    token, filename, pdf_bytes,
                    app_properties={
                        gc.APP_PROP_TEMP: "true",
                        gc.APP_PROP_RESULT: job_id or submission_id,
                        gc.APP_PROP_TOKEN: temp_token,
                        gc.APP_PROP_CREATED: str(int(self._clock())),
                    })
                drive_file_id = uploaded["id"]
                self.client.modify_submission_attachments(
                    token, course_id, coursework_id, submission_id,
                    add_drive_file_ids=[drive_file_id])
        except ClassroomApiError as exc:
            translated = self.translate_error(exc)
            return self._finish_op(op_id, status=translated["status"],
                                   message=translated["message"],
                                   http_status=translated["http"],
                                   error_code=translated["code"],
                                   drive_file_id=drive_file_id)

        # Verify: a 200 is not proof; re-read the submission and Drive.
        try:
            verified = self.client.get_student_submission(
                token, course_id, coursework_id, submission_id)
            really_there = drive_file_id in set(gc.drive_attachment_ids(verified))
            meta = self.client.get_drive_file(token, drive_file_id)
        except ClassroomApiError as exc:
            return self._finish_op(
                op_id, status=STATUS_FAILED,
                message=f"Attachment could not be verified ({exc.status}).",
                http_status=exc.status, error_code="verify_failed",
                drive_file_id=drive_file_id)
        if not really_there or not meta or meta.get("trashed"):
            return self._finish_op(
                op_id, status=STATUS_FAILED,
                message="The report is not confirmed on the submission.",
                error_code="verify_failed", drive_file_id=drive_file_id)

        self.storage.classroom_record_canonical_report(
            submission_id, job_id=job_id or "", drive_file_id=drive_file_id,
            now_iso=_iso_now())
        # Share with this one student, best effort (name is cosmetic).
        if student_id:
            try:
                profile = self.client.get_user_profile(token, student_id)
                email = profile.get("emailAddress")
                if email:
                    self.client.share_drive_file(token, drive_file_id, email)
            except Exception:  # noqa: BLE001 — cosmetic step, must not throw
                log.warning("report share with student was refused or failed")
        return self._finish_op(
            op_id, status=STATUS_PUBLISHED,
            message="Report attached and verified on the submission.",
            drive_file_id=drive_file_id)

    # ---------------------------------------------------------------- helpers

    def _safe_token(self) -> str | None:
        try:
            return self._token()
        except classroom_auth.AuthError as exc:
            log.warning("classroom token unavailable: %s", exc)
            return None

    def _course_of(self, coursework_id: str, submission_id: str) -> str | None:
        """Resolve the owning course from cached Google ids.

        Course and coursework ids are independent Google id spaces: parsing the
        coursework id can only produce a wrong course. The course id is looked
        up from the cached submission row (written at last sync) and falls
        back to the cached coursework row. ``None`` means "not cached" — the
        caller must fail the operation honestly instead of guessing.
        """
        return (
            self.storage.classroom_course_of_submission(submission_id)
            or self.storage.classroom_course_of(coursework_id)
        )


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
