-- Math Checker V6 — schema version 2 (Phase 4 correction jobs).
--
-- A correction job is durable independently of the process-local Phase 3
-- engine registry. The job row is written in `queued` state before any
-- provider call; question rows are inserted in the same transaction that
-- marks the job `completed`, so a completed job can never lack its results.
--
-- Uploaded file contents live in the application data directory only while a
-- job is queued/processing. This schema stores metadata (never paths), so a
-- completed or failed job remains readable after restart without its files.

CREATE TABLE IF NOT EXISTS correction_jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    assignment_title TEXT NOT NULL CHECK (length(trim(assignment_title)) > 0),
    instructions TEXT NOT NULL DEFAULT '',
    mark_scheme_text TEXT NOT NULL DEFAULT '',
    feedback_detail TEXT NOT NULL DEFAULT 'detailed'
        CHECK (feedback_detail IN ('brief', 'detailed')),
    max_score REAL CHECK (max_score IS NULL OR max_score > 0),
    partial_credit INTEGER NOT NULL DEFAULT 1
        CHECK (partial_credit IN (0, 1)),
    engine TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    awarded REAL CHECK (awarded IS NULL OR awarded >= 0),
    out_of REAL CHECK (out_of IS NULL OR out_of >= 0),
    percentage REAL CHECK (
        percentage IS NULL OR (percentage >= 0 AND percentage <= 100)
    ),
    report_status TEXT CHECK (
        report_status IS NULL OR report_status IN ('completed', 'partial')
    ),
    review_required INTEGER NOT NULL DEFAULT 0
        CHECK (review_required IN (0, 1)),
    warnings_json TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    idempotency_key TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    CHECK (awarded IS NULL OR out_of IS NULL OR awarded <= out_of),
    CHECK (status <> 'completed' OR report_status IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_correction_jobs_idempotency
    ON correction_jobs(idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_correction_jobs_status
    ON correction_jobs(status);
CREATE INDEX IF NOT EXISTS idx_correction_jobs_created
    ON correction_jobs(created_at DESC);

CREATE TABLE IF NOT EXISTS correction_job_files (
    job_id TEXT NOT NULL REFERENCES correction_jobs(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('submission', 'mark_scheme')),
    position INTEGER NOT NULL CHECK (position >= 0),
    filename TEXT NOT NULL CHECK (length(trim(filename)) > 0),
    media_type TEXT NOT NULL CHECK (length(trim(media_type)) > 0),
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
    PRIMARY KEY (job_id, role, position)
);

CREATE TABLE IF NOT EXISTS correction_items (
    job_id TEXT NOT NULL REFERENCES correction_jobs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    label TEXT NOT NULL CHECK (length(trim(label)) > 0),
    awarded REAL CHECK (awarded IS NULL OR awarded >= 0),
    out_of REAL CHECK (out_of IS NULL OR out_of >= 0),
    feedback TEXT NOT NULL DEFAULT '',
    criteria_json TEXT NOT NULL DEFAULT '[]',
    student_evidence TEXT NOT NULL DEFAULT '',
    scheme_evidence TEXT NOT NULL DEFAULT '',
    verification TEXT NOT NULL DEFAULT '',
    student_answer TEXT NOT NULL DEFAULT '',
    scheme_answer TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (
        status IN ('marked', 'unresolved', 'unreadable', 'missing', 'ambiguous')
    ),
    warnings_json TEXT NOT NULL DEFAULT '[]',
    review_flags_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (job_id, position),
    UNIQUE (job_id, label),
    CHECK (awarded IS NULL OR out_of IS NULL OR awarded <= out_of)
);

CREATE INDEX IF NOT EXISTS idx_correction_items_job
    ON correction_items(job_id, position);
