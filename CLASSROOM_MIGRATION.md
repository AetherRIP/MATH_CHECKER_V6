# CLASSROOM_MIGRATION.md — V5 → V6 Google Classroom migration

Date: 2026-10-19. Scope: integration and migration only. No correction-engine,
UI-redesign or roadmap changes. Companion documents:
[CLASSROOM_CONFIGURATION.md](CLASSROOM_CONFIGURATION.md) (setup/credentials) and
[CLASSROOM_TEST_REPORT.md](CLASSROOM_TEST_REPORT.md) (test evidence).

## 1. What was inspected in V5 (reference implementation)

V5 lives at `E:\MATH_CHECKER_V5\backend\app\classroom\` (≈5,600 lines). The
migration inspection covered:

| V5 module | Inspected role |
|---|---|
| `auth.py` (250) | OAuth scopes, InstalledAppFlow connect, silent refresh, `invalid_scope` vs expiry distinction, email resolution, secret store |
| `client.py` (594) | REST wrappers (courses, courseWork, studentSubmissions, rosters, Drive read/download), pagination cap, `modifyAttachments`, Drive upload/replace/permissions, `patch_draft_grade` 403 fallback |
| `submissions.py` (549) | Full-state submission tracking (NOT_STARTED … GRADED), roster completeness, idempotent upserts, freshness/staleness |
| `sync.py` (224) | Course/coursework/submissions caching with TTL, deleted-in-Classroom archiving, student-name cache |
| `report_attachment.py` (1395) | Report→Drive→attach→verify pipeline, canonical report replacement, duplicate prevention, honest failure states |
| `managed.py` (739) | Managed-assignment membership (persisted, never inferred), grade-return evidence (`grade_return_state`), publish-op audit rows |
| `naming.py` (150) | "Never append 'Via Math Checker'" naming rule |

## 2. V5 workflow (traced end to end)

1. Teacher connects via `InstalledAppFlow`; refresh token stored in the local
   secret store; granted scopes recorded.
2. Access tokens refresh silently; `invalid_scope` means "reconnect for the
   new drive.file permission", not an expiry.
3. Courses/coursework/submissions sync into SQLite caches keyed by Google's
   stable ids; names are display-only.
4. Submissions (all states + roster) map onto tracking rows; `TURNED_IN` means
   handed in; `CREATED` is deliberately never shown as submitted.
5. The correction engine marks the downloaded attachment; results store
   `courseWorkId + submissionId + userId`.
6. Report PDF renders → appProperties-stamped Drive upload → optional student
   share → `modifyAttachments` on ONE StudentSubmission → re-read to VERIFY.
7. Grade write-back: `draftGrade` always, `assignedGrade` only with the draft,
   `:return` as a separate verified step.
8. Every write records its real Google outcome; a 200 is never treated as
   proof of a grade "returned" or an attachment "verified" without re-reading.

## 3. V5 defects / constraints that shaped the V6 design

- Google only lets the OAuth project that **created** coursework modify its
  submissions; for teacher-made assignments the write is honestly refused
  (`not_supported`), never faked.
- `ModifyAttachmentsRequest` has **no** `removeAttachments` field, so a
  re-correction must PATCH the existing Drive file in place (one canonical
  report per submission).
- Ownership must be verified before attachment (`@OwnerAccessRequired`).
- A 200 from `modifyAttachments` is not proof; re-read the submission.
- `assignedGrade` must never be written without `draftGrade`; `:return` does
  not copy the draft grade.

## 4. What was migrated into V6 (files)

| V6 file | Migrated from |
|---|---|
| `backend/app/classroom/client.py` | V5 `client.py` — REST wrappers, pagination, Drive upload/replace, `modifyAttachments`, grade patching; `urllib` instead of `requests` (V6 carries no HTTP SDK), injectable opener for tests |
| `backend/app/classroom/auth.py` | V5 `auth.py` — scopes, silent refresh, reconnect-on-invalid-scope, connect flow (stdlib loopback flow replaces `InstalledAppFlow`), token stored in `<data>/secrets/classroom_refresh_token` (git-ignored) |
| `backend/app/classroom/service.py` | V5 `sync.py` + `managed.py` + `report_attachment.py` orchestration adapted to V6's `Storage` boundary and `CorrectionJobService`; publish-op audit rows; canonical-report replacement |
| `backend/app/api/classroom.py` | New thin router (status/connect/disconnect/courses/coursework/submissions/publish-ops) using the shared error envelope |
| `backend/app/migrations/003_classroom.sql` | V6-native cache + audit tables |
| `backend/app/config.py` | `MC6_GOOGLE_OAUTH_CLIENT` resolution (path or inline JSON), refresh-token path, `classroom_configured` |
| `frontend` (Settings) | Integration-state diagnostics only; no Classroom UI beyond honest status |

## 5. Identifier mapping (stable ids end to end)

- `classroom_submissions.submission_id` = Google `StudentSubmission.id`.
- `student_id` = Google `userId`; names/emails display-only.
- `classroom_coursework.id` = Google `courseWork.id`; `managed=1` is written
  ONLY when this app created the coursework.
- A V6 correction job links to a submission via
  `classroom_submissions.correction_job_id`.
- Report filenames are `Student_Assignment_Correction_Report.pdf` (sanitised),
  but identity never depends on the name — the canonical-record + Drive
  appProperties prove ownership.

## 6. Automatic grade/report workflow in V6

1. `/api/classroom/status` reports what is configured/connected.
2. `/api/classroom/courses…/submissions` sync caches (read-only TTL cache).
3. Attachments flow into the existing correction pipeline (out of scope to
   change; the engine is untouched).
4. `ClassroomService.attach_report(...)` uploads + attaches + VERIFIES; each
   attempt is one `classroom_publish_ops` row updated with the real result.
5. `ClassroomService.publish_grade(...)` writes draft/assigned grade and
   optionally returns; 403 ProjectPermissionDenied → `not_supported`, never
   "published".

All live Classroom behaviour is GOVERNED BY THE SAME RULES the migration
report documents: no mark is uploaded before the correction result passed
validation (jobs only reach `completed` with a validated report), and no
operation is reported successful without Google's confirmed outcome.
