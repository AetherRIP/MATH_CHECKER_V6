-- Math Checker V6 — schema version 3 (Google Classroom integration).
--
-- Classroom data is a CACHE keyed by Google's stable identifiers; nothing
-- here replaces V6's own students/assignments/corrections tables. Two rules
-- carried over from V5:
--
-- * a CourseWork created by any other project still syncs (read-only) and is
--   marked managed = 0; only coursework this app actually created through the
--   API is managed = 1 (persisted membership, never inferred from a title);
-- * every mutating Classroom call is recorded in classroom_publish_ops with
--   its real outcome, so the UI can distinguish "not yet", "not supported",
--   "failed" and "confirmed published" without inventing any of them.

CREATE TABLE IF NOT EXISTS classroom_courses (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    section TEXT,
    enrollment_code TEXT,
    state TEXT,
    update_time TEXT,
    fetched_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS classroom_coursework (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES classroom_courses(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    classroom_title TEXT,
    max_points REAL,
    state TEXT,
    due_date TEXT,
    alternate_link TEXT,
    description TEXT,
    update_time TEXT,
    fetched_at REAL NOT NULL,
    -- managed = 1 is written ONLY by create_coursework (we own it), never
    -- guessed; managed = 0 means read/sync/correct but expect write refusal.
    managed INTEGER NOT NULL DEFAULT 0 CHECK (managed IN (0, 1)),
    allowlisted INTEGER NOT NULL DEFAULT 0 CHECK (allowlisted IN (0, 1)),
    deleted_in_classroom INTEGER NOT NULL DEFAULT 0 CHECK (deleted_in_classroom IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_classroom_coursework_course
    ON classroom_coursework(course_id);

CREATE TABLE IF NOT EXISTS classroom_submissions (
    -- Google's stable StudentSubmission id: the join key everywhere.
    submission_id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL,
    coursework_id TEXT NOT NULL REFERENCES classroom_coursework(id) ON DELETE CASCADE,
    -- Stable Classroom user id (never a display name).
    student_id TEXT NOT NULL,
    student_name TEXT,
    student_email TEXT,
    attachment_id TEXT,
    attachment_mime TEXT,
    current_state TEXT NOT NULL,
    previous_state TEXT,
    late INTEGER NOT NULL DEFAULT 0 CHECK (late IN (0, 1)),
    -- Classroom grade fields as Google reported them at sync time.
    assigned_grade REAL,
    draft_grade REAL,
    max_points REAL,
    data_quality TEXT NOT NULL DEFAULT 'UNKNOWN'
        CHECK (data_quality IN ('VERIFIED', 'PARTIAL', 'ERROR', 'UNKNOWN')),
    sync_error TEXT,
    -- V6 correction linkage (durable job; may be NULL until first correction).
    correction_job_id TEXT,
    last_synced_at REAL NOT NULL,
    first_seen_at REAL NOT NULL,
    sync_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_classroom_submissions_coursework
    ON classroom_submissions(coursework_id);
CREATE INDEX IF NOT EXISTS idx_classroom_submissions_student
    ON classroom_submissions(student_id);

-- One row per mutating Classroom operation, written BEFORE the call and
-- updated with the true outcome afterwards (never assumed success).
CREATE TABLE IF NOT EXISTS classroom_publish_ops (
    id TEXT PRIMARY KEY,
    coursework_id TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    student_id TEXT,
    op_type TEXT NOT NULL CHECK (
        op_type IN ('draft_grade', 'assign_grade', 'return', 'attach_report')
    ),
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'published', 'failed', 'not_supported',
                   'requires_auth', 'skipped', 'refused')
    ),
    http_status INTEGER,
    error_code TEXT,
    message TEXT,
    drive_file_id TEXT,
    result_job_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_classroom_publish_ops_target
    ON classroom_publish_ops(coursework_id, submission_id);
CREATE INDEX IF NOT EXISTS idx_classroom_publish_ops_created
    ON classroom_publish_ops(created_at DESC);

-- Canonical one-report-per-submission record (Classroom has no
-- removeAttachments; a re-correction must UPDATE our file in place).
CREATE TABLE IF NOT EXISTS classroom_canonical_reports (
    submission_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    drive_file_id TEXT,
    updated_at TEXT NOT NULL
);
