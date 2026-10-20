"""Google Classroom + Drive REST client (stdlib only, V6 architecture).

Migrated from V5's proven ``classroom/client.py`` with the same endpoint
semantics, adapted to V6:

* ``urllib`` instead of ``requests`` (V6 carries no HTTP SDK dependency);
* an injectable ``opener`` so tests mock Google without network access;
* the ``TESTING_ONLY`` publish guard is replaced by a ``publish_allowed``
  constructor flag the API layer sets from the application's settings;
* the grade write-back honours Google's documented rule that ``assignedGrade``
  must never be written without ``draftGrade`` (Google's ``return`` does not
  copy the draft grade), so both fields are written together.

No response body that could echo student content is ever logged; only status
codes and short, safe detail markers reach the log.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger("mathchecker.classroom.client")

CLASSROOM_BASE = "https://classroom.googleapis.com/v1"
DRIVE_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"

# A hard stop so a server that echoes the same nextPageToken forever can
# never spin a listing loop.
MAX_PAGES = 200
# A student submission may hold at most 20 attachments (Google's documented
# limit for ModifyAttachmentSettings).
MAX_SUBMISSION_ATTACHMENTS = 20


class ClassroomApiError(RuntimeError):
    """A Google API call failed. ``detail`` is a short safe marker only."""

    def __init__(self, status: int, detail: str):
        super().__init__(f"Google API error {status}")
        self.status = status
        self.detail = (detail or "")[:500]


def _message_for_status(status: int) -> str:
    if status in (401,):
        return "Google authorization expired or was revoked. Reconnect Google Classroom."
    if status == 403:
        return (
            "Google Classroom refused the operation (insufficient permission). "
            "Only the integration that created an assignment may change its grades "
            "or attachments."
        )
    if status == 404:
        return "Google could not find that course, assignment or submission. Re-sync and retry."
    if status == 429:
        return "Google rate-limited the request. Try again shortly."
    if status >= 500:
        return f"Google reported a server error ({status}). Try again shortly."
    return f"Google rejected the request ({status})."


# Temporary-report markers stamped in Drive appProperties, carried over from
# V5 so cleanup can prove a file is ours before touching it.
APP_PROP_TEMP = "mathcorrectTemp"
APP_PROP_RESULT = "mathcorrectResultId"
APP_PROP_TOKEN = "mathcorrectToken"
APP_PROP_CREATED = "mathcorrectCreatedAt"

_FILE_FIELDS = (
    "id,name,mimeType,owners,createdTime,trashed,driveId,parents,"
    "appProperties,capabilities"
)


class ClassroomClient:
    """Thin REST wrapper. All calls take an access token string.

    ``opener`` is injectable for tests; the default performs real HTTPS via
    ``urllib.request.urlopen``.
    """

    def __init__(self, *, publish_allowed: bool = True, opener=None, transport=None):
        self.publish_allowed = publish_allowed
        self._opener = opener or urllib.request.urlopen
        self._transport = transport or _urllib_transport

    # ------------------------------------------------------------------ core

    def _call(self, method: str, url: str, token: str, *, params=None, body=None,
              headers=None, timeout: int = 60):
        if method != "GET" and not self.publish_allowed:
            raise ClassroomApiError(
                403, "Publishing is disabled (testing-only mode). Reads are unaffected."
            )
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        merged = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        merged.update(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            merged["Content-Type"] = "application/json; charset=UTF-8"
        request = urllib.request.Request(url, data=data, method=method, headers=merged)
        try:
            with self._opener(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            # Never read the error body into logs; a short marker only.
            raise ClassroomApiError(exc.code, _message_for_status(exc.code)) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ClassroomApiError(0, "Google could not be reached. Check the network connection.") from exc
        self._transport(record=len(raw or b""))
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ClassroomApiError(0, "Google returned an unreadable response.") from exc

    # ------------------------------------------------------------- listings

    def _paginate(self, url: str, params: dict, key: str, token: str) -> list[dict]:
        cursor = {**params, "pageSize": params.get("pageSize") or 100}
        items: list[dict] = []
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            data = self._call("GET", url, token, params=cursor)
            items.extend(data.get(key) or [])
            page_token = data.get("nextPageToken")
            if not page_token or page_token in seen:
                break
            seen.add(page_token)
            cursor["pageToken"] = page_token
        return items

    def list_teacher_courses(self, token: str) -> list[dict]:
        return self._paginate(
            f"{CLASSROOM_BASE}/courses",
            {"teacherId": "me", "courseStates": "ACTIVE", "pageSize": 100},
            "courses", token,
        )

    def list_assignments(self, token: str, course_id: str) -> list[dict]:
        items = self._paginate(
            f"{CLASSROOM_BASE}/courses/{course_id}/courseWork",
            {"courseWorkStates": "PUBLISHED", "pageSize": 100},
            "courseWork", token,
        )
        return [item for item in items if item.get("workType") == "ASSIGNMENT"]

    def list_turned_in_submissions(self, token: str, course_id: str, coursework_id: str) -> list[dict]:
        return self._paginate(
            f"{CLASSROOM_BASE}/courses/{course_id}/courseWork/{coursework_id}/studentSubmissions",
            {"states": "TURNED_IN", "pageSize": 100},
            "studentSubmissions", token,
        )

    def list_student_submissions(self, token: str, course_id: str, coursework_id: str) -> list[dict]:
        """Every submission in every state (roster completeness, V5 §4)."""
        return self._paginate(
            f"{CLASSROOM_BASE}/courses/{course_id}/courseWork/{coursework_id}/studentSubmissions",
            {"pageSize": 100},
            "studentSubmissions", token,
        )

    def list_course_students(self, token: str, course_id: str) -> list[dict]:
        return self._paginate(
            f"{CLASSROOM_BASE}/courses/{course_id}/students",
            {"pageSize": 100},
            "students", token,
        )

    def get_user_profile(self, token: str, user_id: str) -> dict:
        return self._call("GET", f"{CLASSROOM_BASE}/userProfiles/{user_id}", token)

    def get_student_submission(self, token: str, course_id: str,
                               coursework_id: str, submission_id: str) -> dict:
        return self._call(
            "GET",
            f"{CLASSROOM_BASE}/courses/{course_id}/courseWork/{coursework_id}"
            f"/studentSubmissions/{submission_id}",
            token,
        )

    # ------------------------------------------------------------- Drive read

    def download_drive_file(self, token: str, file_id: str) -> tuple[str, bytes, str]:
        """Download a Drive attachment; Google Docs are exported to PDF."""
        meta = self._call("GET", f"{DRIVE_BASE}/files/{file_id}", token,
                          params={"fields": "id,name,mimeType,capabilities"})
        name = meta.get("name", f"drive_file_{file_id}")
        mime = meta.get("mimeType", "application/octet-stream")
        capabilities = meta.get("capabilities") or {}
        if capabilities.get("canDownload") is False:
            raise ClassroomApiError(403, "Google Drive does not allow downloading this file.")
        if mime == "application/vnd.google-apps.document":
            request = urllib.request.Request(
                f"{DRIVE_BASE}/files/{file_id}/export",
                headers={"Authorization": f"Bearer {token}"},
            )
            try:
                with self._opener(request, timeout=120) as response:
                    content = response.read()
            except urllib.error.HTTPError as exc:
                raise ClassroomApiError(exc.code, "Could not export the Google Doc to PDF.") from exc
            self._transport(record=len(content))
            stem = name.rsplit(".", 1)[0] if "." in name else name
            return f"{stem}.pdf", content, "application/pdf"
        request = urllib.request.Request(
            f"{DRIVE_BASE}/files/{file_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with self._opener(request, timeout=180) as response:
                content = response.read()
        except urllib.error.HTTPError as exc:
            raise ClassroomApiError(exc.code, "Could not download the Drive file.") from exc
        self._transport(record=len(content))
        return name, content, mime

    def get_drive_file(self, token: str, file_id: str) -> dict | None:
        try:
            return self._call("GET", f"{DRIVE_BASE}/files/{file_id}", token,
                              params={"fields": _FILE_FIELDS, "supportsAllDrives": "true"},
                              timeout=30)
        except ClassroomApiError as exc:
            if exc.status == 404:
                return None
            raise

    # ------------------------------------------------------------- write-back

    def create_coursework(self, token: str, course_id: str, body: dict) -> dict:
        return self._call("POST", f"{CLASSROOM_BASE}/courses/{course_id}/courseWork",
                          token, body=body)

    def upload_report_to_drive(self, token: str, filename: str, content: bytes, *,
                               app_properties: dict | None = None,
                               folder_id: str | None = None) -> dict:
        """Multipart upload of one PDF report to Drive (drive.file scope)."""
        if not self.publish_allowed:
            raise ClassroomApiError(403, "Publishing is disabled (testing-only mode).")
        metadata: dict = {"name": filename, "mimeType": "application/pdf"}
        if app_properties:
            metadata["appProperties"] = {str(k): str(v)[:200] for k, v in app_properties.items()}
        if folder_id:
            metadata["parents"] = [folder_id]
        boundary = "mc6-report-boundary"
        payload = (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata)}\r\n"
            f"--{boundary}\r\n"
            "Content-Type: application/pdf\r\n\r\n"
        ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
        request = urllib.request.Request(
            f"{DRIVE_UPLOAD_BASE}/files?uploadType=multipart"
            f"&fields=id,name,mimeType,owners,createdTime,appProperties",
            data=payload, method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
        )
        try:
            with self._opener(request, timeout=180) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise ClassroomApiError(exc.code, _message_for_status(exc.code)) from exc
        self._transport(record=len(payload), sent=len(content))
        return json.loads(raw.decode("utf-8"))

    def replace_drive_file_content(self, token: str, file_id: str, content: bytes) -> None:
        """Overwrite a Drive file's bytes (PATCH, not POST — Drive v3 files.update)."""
        if not self.publish_allowed:
            raise ClassroomApiError(403, "Publishing is disabled (testing-only mode).")
        request = urllib.request.Request(
            f"{DRIVE_UPLOAD_BASE}/files/{file_id}?uploadType=media&fields=id,name,size",
            data=content, method="PATCH",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/pdf"},
        )
        try:
            with self._opener(request, timeout=180) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            raise ClassroomApiError(exc.code, _message_for_status(exc.code)) from exc
        self._transport(record=len(content), sent=len(content))

    def share_drive_file(self, token: str, file_id: str, email: str,
                         role: str = "reader") -> dict:
        """Grant ONE named user read access. Ownership transfer is refused."""
        if role == "owner":
            raise ClassroomApiError(
                400,
                "Refusing to transfer report ownership to a student: Classroom "
                "attachment requires this app to own the file.",
            )
        return self._call("POST", f"{DRIVE_BASE}/files/{file_id}/permissions", token,
                          body={"type": "user", "role": role, "emailAddress": email})

    def modify_submission_attachments(self, token: str, course_id: str,
                                       coursework_id: str, submission_id: str, *,
                                       add_drive_file_ids: list[str]) -> dict:
        """Add Drive attachments to ONE student's submission (addAttachments only)."""
        if not self.publish_allowed:
            raise ClassroomApiError(403, "Publishing is disabled (testing-only mode).")
        body = {"addAttachments": [{"driveFile": {"id": fid}} for fid in add_drive_file_ids]}
        return self._call(
            "POST",
            f"{CLASSROOM_BASE}/courses/{course_id}/courseWork/{coursework_id}"
            f"/studentSubmissions/{submission_id}:modifyAttachments",
            token, body=body,
        )

    def patch_grade_fields(self, token: str, course_id: str, coursework_id: str,
                           submission_id: str, *, grade: float,
                           assigned: bool) -> dict:
        """Write draftGrade (and assignedGrade when returning) for a submission.

        Google only lets an OAuth project grade coursework it created; the 403
        surfaces as :class:`ClassroomApiError` and the caller records the real
        result rather than pretending the grade landed.
        """
        if not self.publish_allowed:
            raise ClassroomApiError(403, "Publishing is disabled (testing-only mode).")
        update_mask = "draftGrade,assignedGrade" if assigned else "draftGrade"
        body: dict = {"draftGrade": float(grade)}
        if assigned:
            body["assignedGrade"] = float(grade)
        return self._call(
            "PATCH",
            f"{CLASSROOM_BASE}/courses/{course_id}/courseWork/{coursework_id}"
            f"/studentSubmissions/{submission_id}",
            token, params={"updateMask": update_mask}, body=body,
        )

    def return_submission(self, token: str, course_id: str, coursework_id: str,
                          submission_id: str) -> dict:
        """Return ONE student submission so the student sees the grade."""
        if not self.publish_allowed:
            raise ClassroomApiError(403, "Publishing is disabled (testing-only mode).")
        return self._call(
            "POST",
            f"{CLASSROOM_BASE}/courses/{course_id}/courseWork/{coursework_id}"
            f"/studentSubmissions/{submission_id}:return",
            token, body={},
        )


def _urllib_transport(*, record: int, sent: int | None = None) -> None:
    """Placeholder for V6's network meter; keeps client signature testable."""
    return None


def extract_attachments(submission: dict) -> list[dict]:
    """Normalise a StudentSubmission's attachments (V5 parity)."""
    out: list[dict] = []
    for att in (submission.get("assignmentSubmission") or {}).get("attachments", []) or []:
        if att.get("driveFile"):
            drive = att["driveFile"]
            out.append({"kind": "drive", "id": drive.get("id"),
                        "title": drive.get("title") or drive.get("id")})
        elif att.get("form"):
            out.append({"kind": "form", "id": att["form"].get("formId"),
                        "title": att["form"].get("title")})
        elif att.get("link"):
            out.append({"kind": "link", "id": att["link"].get("url"),
                        "title": att["link"].get("url")})
        elif att.get("youTubeVideo"):
            out.append({"kind": "youtube", "id": att["youTubeVideo"].get("id"),
                        "title": att["youTubeVideo"].get("title")})
    return out


def drive_attachment_ids(submission: dict) -> list[str]:
    ids: list[str] = []
    for attachment in (submission.get("assignmentSubmission") or {}).get("attachments", []) or []:
        drive = attachment.get("driveFile") or {}
        if drive.get("id"):
            ids.append(drive["id"])
    return ids


def submission_can_be_modified(submission: dict) -> bool:
    """``associatedWithDeveloper`` gates write-back before an upload is spent."""
    return bool(submission.get("associatedWithDeveloper"))


def is_our_temp_report(meta: dict | None, *, result_id: str | None = None) -> bool:
    """Can we PROVE this Drive file is a temporary report this app created?"""
    if not meta or meta.get("trashed"):
        return False
    props = meta.get("appProperties") or {}
    if str(props.get(APP_PROP_TEMP)).lower() != "true":
        return False
    if result_id and str(props.get(APP_PROP_RESULT) or "") != str(result_id):
        return False
    return True


def drive_file_owners(meta: dict | None) -> list[str]:
    return [str(owner.get("emailAddress", "")).lower()
            for owner in ((meta or {}).get("owners") or []) if owner.get("emailAddress")]


import urllib.parse  # noqa: E402  (used by _call; kept at end for import order)
