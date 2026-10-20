-- Math Checker V6 — schema version 1 (Phase 2 backend foundation).
--
-- Rules encoded here:
--   * Marks are NULL only when absent; zero is a real mark.
--   * Missing, draft and submitted work have distinct states.
--   * Lesson codes are opaque text and are never normalised.
--   * Correction results are one-per-submission and belong to the submission.

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS students (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    email TEXT,
    external_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_students_external_id
    ON students(external_id)
    WHERE external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS assignments (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    qualification TEXT NOT NULL DEFAULT 'Edexcel IGCSE Mathematics',
    component TEXT NOT NULL DEFAULT '',
    lesson_code TEXT,
    notes TEXT NOT NULL DEFAULT '',
    max_score REAL CHECK (max_score IS NULL OR max_score >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_assignments_lesson_code
    ON assignments(lesson_code);

CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY,
    assignment_id TEXT NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('missing', 'draft', 'submitted', 'graded', 'failed')),
    original_filename TEXT,
    media_type TEXT,
    size_bytes INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
    submitted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(assignment_id, student_id),
    CHECK (
        (status IN ('missing', 'draft') AND submitted_at IS NULL)
        OR
        (status IN ('submitted', 'graded', 'failed') AND submitted_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_submissions_assignment
    ON submissions(assignment_id);
CREATE INDEX IF NOT EXISTS idx_submissions_student
    ON submissions(student_id);
CREATE INDEX IF NOT EXISTS idx_submissions_status
    ON submissions(status);

CREATE TABLE IF NOT EXISTS correction_results (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL UNIQUE REFERENCES submissions(id) ON DELETE CASCADE,
    outcome TEXT NOT NULL CHECK (outcome IN ('completed', 'failed')),
    awarded REAL,
    out_of REAL,
    summary TEXT NOT NULL DEFAULT '',
    feedback TEXT NOT NULL DEFAULT '',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (
            outcome = 'completed'
            AND awarded IS NOT NULL
            AND out_of IS NOT NULL
            AND awarded >= 0
            AND out_of >= 0
            AND awarded <= out_of
        )
        OR
        (
            outcome = 'failed'
            AND awarded IS NULL
            AND out_of IS NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_correction_results_outcome
    ON correction_results(outcome);
