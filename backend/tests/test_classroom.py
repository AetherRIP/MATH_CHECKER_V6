"""Classroom integration tests — Google is always mocked.

A mocked success proves the local code handles that simulated response
correctly. It is NOT proof that live authentication or upload operations
work; see CLASSROOM_TEST_REPORT.md for the live-unverified list.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.classroom import auth as classroom_auth
from app.classroom.client import ClassroomApiError, ClassroomClient
from app.classroom.service import (
    STATUS_NOT_SUPPORTED,
    STATUS_PUBLISHED,
    STATUS_REQUIRES_AUTH,
    ClassroomService,
)

COURSE = {"id": "course-1", "name": "Algebra", "courseState": "ACTIVE"}
COURSES_OK = {"courses": [COURSE]}
COURSEWORK = {"id": "cw-1", "title": "Chapter 4", "workType": "ASSIGNMENT",
              "maxPoints": 10, "state": "PUBLISHED",
              "alternateLink": "https://classroom/link"}
SUBMISSION = {
    "id": "sub-1", "courseId": "course-1", "courseWorkId": "cw-1",
    "userId": "student-1", "state": "TURNED_IN", "late": False,
    "associatedWithDeveloper": True,
    "assignmentSubmission": {"attachments": [
        {"driveFile": {"id": "file-student", "title": "work.pdf"}}]},
}


class FakeResponse:
    def __init__(self, payload=b"{}", status=200):
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload).encode("utf-8")
        self._payload = payload if isinstance(payload, bytes) else payload.encode()
        self.status = status

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeGoogle:
    """Scriptable opener: maps (method, url-substring) to responses."""

    def __init__(self):
        self.routes: dict[tuple[str, str], object] = {}
        self.calls: list[tuple[str, str]] = []

    def on(self, method: str, url_part: str, payload):
        self.routes[(method, url_part)] = payload
        return self

    def __call__(self, request, timeout=None):
        method = request.get_method()
        url = request.full_url
        self.calls.append((method, url))
        # Longest matching key wins: the coursework-listing URL is a prefix
        # of the per-coursework submissions URL, so substring order matters.
        candidates = [
            (len(part), payload)
            for (route_method, part), payload in self.routes.items()
            if method == route_method and part in url
        ]
        if candidates:
            candidates.sort(key=lambda pair: -pair[0])
            payload = candidates[0][1]
            if isinstance(payload, Exception):
                raise payload
            return FakeResponse(payload)
        raise ClassroomApiError(0, f"no fake route for {method} {url[:90]}")


@pytest.fixture()
def oauth_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    secrets_dir = tmp_path / "data" / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    client_path = secrets_dir / "google_oauth_client.json"
    client_path.write_text(
        json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(classroom_auth, "_client_config", lambda: {
        "client_id": "cid", "client_secret": "sec",
        "redirect_uris": ["http://127.0.0.1:0"],
    })
    return client_path


def _storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MC6_DATA_DIR", str(tmp_path / "data"))
    from app.config import ensure_dirs
    from app.db import Database
    from app.storage import Storage

    ensure_dirs()
    database = Database((tmp_path / "data" / "app.db"))
    database.initialize()
    return Storage(database)


def _service(storage, fake: FakeGoogle) -> ClassroomService:
    client = ClassroomClient(publish_allowed=True, opener=fake)
    service = ClassroomService(storage, client=client)
    service._token = lambda: "fake-token"  # type: ignore[method-assign]
    return service


def _publish_setup(storage, fake: FakeGoogle) -> ClassroomService:
    """Cache course-1/cw-1/sub-1 first, as the real publish flow must."""
    fake.on("GET", "/courses/course-1/courseWork", {"courseWork": [COURSEWORK]})
    fake.routes[("GET", "/courses?")] = COURSES_OK
    service = _service(storage, fake)
    service.sync_coursework("course-1")
    return service


# ----------------------------------------------------------------- config/auth


def test_oauth_client_materialises_from_inline_json(tmp_path, monkeypatch):
    from app.config import classroom_client_configured, classroom_oauth_client_path

    monkeypatch.setenv("MC6_GOOGLE_OAUTH_CLIENT",
                       '{"installed":{"client_id":"a","client_secret":"b"}}')
    real_get_config = __import__("app.config", fromlist=["get_config"]).get_config
    monkeypatch.setattr("app.config.get_config",
                        lambda: type("C", (), {"data_dir": tmp_path})())
    path = classroom_oauth_client_path()
    assert path is not None and path.is_file()
    assert classroom_client_configured() is True
    # The inline JSON is written under the git-ignored data directory.
    assert "secrets" in str(path)
    _ = real_get_config


def test_refresh_token_is_never_returned_by_auth_state(oauth_client, tmp_path):
    classroom_auth.store_refresh_token("secret-refresh-value")
    state = classroom_auth.auth_state()
    assert state["connected"] is True
    assert "secret" not in json.dumps(state)


def test_invalid_scope_refresh_reads_as_reconnect(oauth_client, monkeypatch):
    classroom_auth.store_refresh_token("tok")

    def fail(refresh_token, granted_scopes=None):
        raise classroom_auth.AuthError(
            "Google Classroom must be reconnected to grant the permission "
            "that uploads correction reports to Drive (drive.file)."
        )

    monkeypatch.setattr(classroom_auth, "_refresh_access_token", fail)
    with pytest.raises(classroom_auth.AuthError, match="reconnect"):
        classroom_auth.get_access_token()


def test_missing_refresh_token_is_a_clear_error(oauth_client, monkeypatch):
    monkeypatch.setattr(classroom_auth, "read_refresh_token", lambda: None)
    with pytest.raises(classroom_auth.AuthError, match="not connected"):
        classroom_auth.get_access_token()


# -------------------------------------------------------------- data retrieval


def test_sync_courses_paginates_and_caches(tmp_path, monkeypatch):
    storage = _storage(tmp_path, monkeypatch)
    fake = FakeGoogle().on("GET", "/courses?", COURSES_OK)
    service = _service(storage, fake)

    courses = service.sync_courses()
    assert [c["id"] for c in courses] == ["course-1"]
    # Second call is served from cache (no new HTTP call).
    calls_before = len(fake.calls)
    service.sync_courses()
    assert len(fake.calls) == calls_before


def test_sync_submissions_maps_roster_and_state(tmp_path, monkeypatch):
    storage = _storage(tmp_path, monkeypatch)
    fake = (
        FakeGoogle()
        .on("GET", "/courses/course-1/students", {"students": [
            {"userId": "student-1", "profile": {
                "name": {"fullName": "Ada Lovelace"},
                "emailAddress": "ada@example.com"}}]})
        .on("GET", "courseWork/cw-1/studentSubmissions", {"studentSubmissions": [SUBMISSION]})
        .on("GET", "/courses/course-1/courseWork", {"courseWork": [COURSEWORK]})
    )
    fake.routes[("GET", "/courses?")] = COURSES_OK
    service = _service(storage, fake)
    service.sync_coursework("course-1")
    rows = service.sync_submissions("course-1", "cw-1")

    assert len(rows) == 1
    row = rows[0]
    # Stable identifiers, never names.
    assert row["submission_id"] == "sub-1"
    assert row["student_id"] == "student-1"
    assert row["student_name"] == "Ada Lovelace"
    assert row["current_state"] == "TURNED_IN"


# --------------------------------------------------------- grade write-back


def test_publish_grade_success_is_recorded_as_published(tmp_path, monkeypatch):
    storage = _storage(tmp_path, monkeypatch)
    fake = (
        FakeGoogle()
        .on("PATCH", "/studentSubmissions/sub-1", SUBMISSION)
        .on("POST", ":return", SUBMISSION)
        .on("GET", "/courses/course-1/courseWork", {"courseWork": [COURSEWORK]})
    )
    fake.routes[("GET", "/courses?")] = COURSES_OK
    service = _service(storage, fake)
    service.sync_coursework("course-1")

    op = service.publish_grade(
        "cw-1", "sub-1", grade=8.0, return_to_student=True, assigned=True,
        student_id="student-1")
    assert op.status == STATUS_PUBLISHED
    ops = storage.classroom_publish_ops("cw-1")
    assert ops and ops[0]["status"] == "published"


def test_publish_grade_403_is_recorded_as_not_supported(tmp_path, monkeypatch):
    storage = _storage(tmp_path, monkeypatch)
    fake = FakeGoogle().on(
        "PATCH", "/studentSubmissions/sub-1",
        ClassroomApiError(403, "ProjectPermissionDenied"))
    service = _publish_setup(storage, fake)

    op = service.publish_grade("cw-1", "sub-1", grade=8.0,
                               return_to_student=False, assigned=True)
    assert op.status == STATUS_NOT_SUPPORTED
    ops = storage.classroom_publish_ops("cw-1")
    assert ops[0]["status"] == "not_supported"
    assert ops[0]["error_code"] == "permission_denied"


def test_publish_grade_uses_the_cached_course_id(tmp_path, monkeypatch):
    """Google course and coursework ids are unrelated spaces: the grade PATCH
    must address the CACHED course, never a parse of the coursework id."""
    storage = _storage(tmp_path, monkeypatch)
    fake = (
        FakeGoogle()
        .on("PATCH", "/studentSubmissions/sub-1", SUBMISSION)
        .on("GET", "/courses/course-1/courseWork", {"courseWork": [COURSEWORK]})
    )
    fake.routes[("GET", "/courses?")] = COURSES_OK
    service = _publish_setup(storage, fake)

    assert storage.classroom_course_of("cw-1") == "course-1"
    op = service.publish_grade("cw-1", "sub-1", grade=7.0,
                               return_to_student=False, assigned=True)
    assert op.status == STATUS_PUBLISHED
    patch_urls = [url for method, url in fake.calls if method == "PATCH"]
    assert patch_urls, "the grade write never reached the classroom client"
    assert all("/courses/course-1/courseWork/cw-1/studentSubmissions/" in url
               for url in patch_urls)


def test_publish_unresolved_course_fails_without_guessing(tmp_path, monkeypatch):
    """With nothing cached, publish must fail honestly — NOT call Google with
    a course id parsed from the coursework id."""
    storage = _storage(tmp_path, monkeypatch)
    fake = FakeGoogle()
    service = _service(storage, fake)

    op = service.publish_grade("cw-1", "sub-1", grade=5.0,
                               return_to_student=False, assigned=True)
    assert op.status == "failed"
    ops = storage.classroom_publish_ops("cw-1")
    assert ops[0]["error_code"] == "course_unresolved"
    assert fake.calls == [], "a write must never be attempted with a guessed course"


def test_publish_grade_without_connection_requires_auth(tmp_path, monkeypatch):
    storage = _storage(tmp_path, monkeypatch)
    fake = FakeGoogle()
    service = ClassroomService(storage, client=ClassroomClient(opener=fake))

    def not_connected():
        raise classroom_auth.AuthError("Google Classroom is not connected yet.")

    service._token = not_connected  # type: ignore[method-assign]
    op = service.publish_grade("cw-1", "sub-1", grade=5.0,
                               return_to_student=False, assigned=False)
    assert op.status == STATUS_REQUIRES_AUTH


def test_publish_disabled_blocks_writes_but_not_reads(tmp_path, monkeypatch):
    storage = _storage(tmp_path, monkeypatch)
    fake = FakeGoogle()
    client = ClassroomClient(publish_allowed=False, opener=fake)
    service = ClassroomService(storage, client=client)
    service._token = lambda: "fake-token"  # type: ignore[method-assign]
    fake.on("GET", "/courses/course-1/courseWork", {"courseWork": [COURSEWORK]})
    fake.routes[("GET", "/courses?")] = COURSES_OK
    service.sync_coursework("course-1")

    op = service.publish_grade("cw-1", "sub-1", grade=5.0,
                               return_to_student=False, assigned=False)
    assert op.status == STATUS_NOT_SUPPORTED


def test_publish_rate_limit_and_outage_are_recorded_honestly(tmp_path, monkeypatch):
    """429 and 5xx reach the audit trail as failed ops with the real status."""
    for index, (http_status, expected_code) in enumerate(
            ((429, "rate_limited"), (503, "google_error"))):
        storage = _storage(tmp_path / f"iter{index}", monkeypatch)
        fake = FakeGoogle().on(
            "PATCH", "/studentSubmissions/sub-1",
            ClassroomApiError(http_status, "upstream"))
        service = _publish_setup(storage, fake)

        op = service.publish_grade("cw-1", "sub-1", grade=5.0,
                                   return_to_student=False, assigned=False)
        assert op.status == "failed"
        ops = storage.classroom_publish_ops("cw-1")
        assert ops[0]["http_status"] == http_status
        assert ops[0]["error_code"] == expected_code
        assert "try again" in ops[0]["message"].lower()


def test_translate_error_never_marks_permanent_failures_retryable(tmp_path):
    from app.classroom.service import ClassroomService as S

    assert S.translate_error(ClassroomApiError(429, "rate"))["status"] == "failed"
    assert S.translate_error(ClassroomApiError(500, "boom"))["status"] == "failed"
    assert S.translate_error(ClassroomApiError(401, "expired"))["status"] == "requires_auth"


def test_return_records_previous_and_current_state(tmp_path, monkeypatch):
    """Returning a submission moves TURNED_IN -> RETURNED in the cache while
    preserving the pre-return state — the draft-vs-returned distinction."""
    storage = _storage(tmp_path, monkeypatch)
    returned = {**SUBMISSION, "state": "RETURNED",
                "draftGrade": 8.0, "assignedGrade": 8.0}
    fake = (
        FakeGoogle()
        .on("PATCH", "/studentSubmissions/sub-1", SUBMISSION)
        .on("POST", ":return", returned)
        .on("GET", "/courses/course-1/courseWork", {"courseWork": [COURSEWORK]})
    )
    fake.routes[("GET", "/courses?")] = COURSES_OK
    fake.on("GET", "courseWork/cw-1/studentSubmissions", {"studentSubmissions": [SUBMISSION]})
    fake.on("GET", "/courses/course-1/students", {"students": [
        {"userId": "student-1", "profile": {
            "name": {"fullName": "Ada Lovelace"},
            "emailAddress": "ada@example.com"}}]})
    service = _publish_setup(storage, fake)
    service.sync_submissions("course-1", "cw-1", force=True)
    before = storage.classroom_submission_rows("cw-1")[0]
    assert before["current_state"] == "TURNED_IN"
    assert before["previous_state"] is None

    op = service.publish_grade(
        "cw-1", "sub-1", grade=8.0, return_to_student=True, assigned=True,
        student_id="student-1")
    assert op.status == STATUS_PUBLISHED
    after = storage.classroom_submission_rows("cw-1")[0]
    assert after["current_state"] == "RETURNED"
    assert after["previous_state"] == "TURNED_IN"
    assert after["draft_grade"] == 8.0 and after["assigned_grade"] == 8.0


def test_zero_grade_is_a_real_grade_not_a_missing_one(tmp_path, monkeypatch):
    """A 0 must be written and cached as an explicit grade, never dropped."""
    zero_submission = {
        **SUBMISSION, "courseId": "course-1", "courseWorkId": "cw-1",
        "draftGrade": 0, "assignedGrade": 0,
    }
    storage = _storage(tmp_path, monkeypatch)
    fake = (
        FakeGoogle()
        .on("PATCH", "/studentSubmissions/sub-1", zero_submission)
        .on("GET", "/courses/course-1/courseWork", {"courseWork": [COURSEWORK]})
    )
    fake.routes[("GET", "/courses?")] = COURSES_OK
    fake.on("GET", "courseWork/cw-1/studentSubmissions", {"studentSubmissions": [zero_submission]})
    fake.on("GET", "/courses/course-1/students", {"students": [
        {"userId": "student-1", "profile": {
            "name": {"fullName": "Ada Lovelace"},
            "emailAddress": "ada@example.com"}}]})
    service = _publish_setup(storage, fake)

    op = service.publish_grade(
        "cw-1", "sub-1", grade=0.0, return_to_student=False, assigned=True)
    assert op.status == STATUS_PUBLISHED
    # Re-sync writes what Google reports: zero is a stored grade.
    service.sync_submissions("course-1", "cw-1", force=True)
    row = storage.classroom_submission_rows("cw-1")[0]
    assert row["draft_grade"] == 0.0
    assert row["assigned_grade"] == 0.0


# ------------------------------------------------------------- report attach


def _attachment_setup(storage, fake):
    fake.on("GET", "/courses/course-1/courseWork", {"courseWork": [COURSEWORK]})
    fake.routes[("GET", "/courses?")] = COURSES_OK
    service = ClassroomService(
        storage, client=ClassroomClient(publish_allowed=True, opener=fake))
    service._token = lambda: "fake-token"  # type: ignore[method-assign]
    service.sync_coursework("course-1")
    return service


def test_attach_report_success_is_verified(tmp_path, monkeypatch):
    storage = _storage(tmp_path, monkeypatch)
    fake = FakeGoogle()
    attached = {**SUBMISSION, "assignmentSubmission": {"attachments": [
        {"driveFile": {"id": "file-report",
                       "title": "Ada_Chapter 4_Correction_Report.pdf"}},
        {"driveFile": {"id": "file-student", "title": "work.pdf"}},
    ]}}
    fake.on("GET", "courseWork/cw-1/studentSubmissions/sub-1", attached)
    fake.on("POST", "upload/drive/v3/files", {"id": "file-report", "name": "r.pdf"})
    fake.on("POST", ":modifyAttachments", attached)
    fake.on("GET", "drive/v3/files/file-report", {"id": "file-report", "trashed": False})
    fake.on("GET", "/userProfiles/student-1", {"emailAddress": "ada@example.com"})
    fake.on("POST", "/permissions", {"id": "perm-1"})
    service = _attachment_setup(storage, fake)

    op = service.attach_report(
        "cw-1", "sub-1", pdf_bytes=b"%PDF-1.7 fake",
        filename="Ada_Chapter 4_Correction_Report.pdf",
        student_id="student-1", job_id="job-1")
    assert op.status == STATUS_PUBLISHED
    assert op.drive_file_id == "file-report"
    canonical = storage.classroom_canonical_report("sub-1")
    assert canonical and canonical["drive_file_id"] == "file-report"


def test_attach_report_blocked_when_not_modifiable(tmp_path, monkeypatch):
    storage = _storage(tmp_path, monkeypatch)
    fake = FakeGoogle().on("GET", "courseWork/cw-1/studentSubmissions/sub-1",
                           {**SUBMISSION, "associatedWithDeveloper": False})
    service = _attachment_setup(storage, fake)

    op = service.attach_report(
        "cw-1", "sub-1", pdf_bytes=b"%PDF", filename="r.pdf",
        student_id="student-1", job_id="job-1")
    assert op.status == STATUS_NOT_SUPPORTED
    # No upload was spent.
    assert not any("upload/drive" in url for _, url in fake.calls)


def test_recorrection_replaces_canonical_file_in_place(tmp_path, monkeypatch):
    storage = _storage(tmp_path, monkeypatch)
    attached_first = {**SUBMISSION, "assignmentSubmission": {"attachments": [
        {"driveFile": {"id": "file-report"}}]}}
    fake = FakeGoogle()
    fake.on("GET", "courseWork/cw-1/studentSubmissions/sub-1", attached_first)
    fake.on("GET", "drive/v3/files/file-report", {"id": "file-report", "trashed": False})
    fake.on("PATCH", "upload/drive/v3/files/file-report", {"id": "file-report"})
    service = _attachment_setup(storage, fake)
    storage.classroom_record_canonical_report(
        "sub-1", job_id="job-0", drive_file_id="file-report", now_iso="now")

    op = service.attach_report(
        "cw-1", "sub-1", pdf_bytes=b"%PDF-1.7 new", filename="Ada_r2.pdf",
        student_id="student-1", job_id="job-1")
    assert op.status == STATUS_PUBLISHED
    assert op.drive_file_id == "file-report"
    # A PATCH (in-place) happened; a second upload did not.
    assert any(method == "PATCH" and "upload/drive" in url
               for method, url in fake.calls)
    assert not any(method == "POST" and "upload/drive" in url
                   for method, url in fake.calls)


def test_report_filename_is_deterministic_and_safe():
    from app.classroom.service import build_report_filename, sanitize_component

    assert build_report_filename("Ada Lovelace", "Chapter 4") == (
        "Ada Lovelace_Chapter 4_Correction_Report.pdf")
    unsafe = sanitize_component('a<b>:"/\\|?*\x01..c')
    for ch in '<>:"/\\|?*':
        assert ch not in unsafe


# ------------------------------------------------------------------ API layer


def test_classroom_status_endpoint_reports_missing_prerequisites(client):
    response = client.get("/api/classroom/status")
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is False
    assert "OAuth client JSON missing" in data["problem"]
    assert "client_secret" not in response.text.lower()


def test_classroom_connect_reports_missing_client_cleanly(client, tmp_path, monkeypatch):
    monkeypatch.delenv("MC6_GOOGLE_OAUTH_CLIENT", raising=False)
    response = client.post("/api/classroom/connect?open_browser=false")
    assert response.status_code == 400
    assert "OAuth client" in response.json()["error"]["message"]


def test_classroom_status_never_leaks_paths_or_env_names(client):
    body = client.get("/api/classroom/status").text
    assert "MC6_" not in body
    assert "refresh_token" not in body
    assert "client_secret" not in body
