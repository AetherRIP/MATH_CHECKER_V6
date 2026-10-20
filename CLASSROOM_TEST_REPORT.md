# CLASSROOM_TEST_REPORT.md — verification evidence (V6 Classroom integration)

Companions: [CLASSROOM_MIGRATION.md](CLASSROOM_MIGRATION.md),
[CLASSROOM_CONFIGURATION.md](CLASSROOM_CONFIGURATION.md).

## 1. Automated suite

```
PYTHONPATH=backend .venv/Scripts/python -m pytest backend/tests
```

Final state at time of writing:

| Suite | Result |
|---|---|
| `backend/tests/test_classroom.py` | **17/17 pass** |
| full backend suite | **202 passed** (`202 passed, 1 warning in 13.76s`) |
| frontend `node --test tests/*.test.mjs` | **49 pass, 0 fail** (unchanged by this work — no frontend file was modified) |

Note: invoking `node --test tests` (directory form) is unreliable with 0.x test runners; use the glob form above.

## 2. What the classroom tests simulate

`FakeClassroomClient` in [test_classroom.py](backend/tests/test_classroom.py)
serves a fixture Classroom API over routes:

- `GET /courses` → one course `course-1`
- `GET /courses/course-1/courseWork` → coursework `cw-1`
- `GET /courses/course-1/courseWork/cw-1/studentSubmissions`
- `GET /courses/course-1/students` → one student with `fullName` + `emailAddress`
- `PATCH /courses/course-1/courseWork/cw-1/studentSubmissions/sub-1`
- `POST /drive/v3/files/…` (upload) and `POST /drive/v3/files/…/permissions`
- `GET /drive/v3/files/att-1` (attachment verification)

They assert the full lifecycle against the real service/storage code paths:
`sync_courses → sync_coursework (auto-syncs courses) → sync_submissions`,
correct cache writes (schema v2 tables), roster enrichment, attachment-need
classification, and error mapping.

## 3. Degraded-mode and auth-noop behaviour

- `classroom_configured` reported honestly from the environment only
  (`test_api_system.py`, `test_config.py`).
- With no credentials the Classroom API never crashes and never fabricates
  data (the integration returns explicit `not_configured` states).

## 4. Manually verified invariants (no live Classroom in CI)

- The OAuth flow sends `access_type=offline&prompt=consent`; the refresh
  token is only written after Google returns a non-empty refresh token.
- `/api/classroom/status` predicate values are honest (constructor state, not
  optimistic).
- Secrets stay in `data/secrets/**` (git-ignored); no test asserts otherwise
  because tests never write a token fixture into the data dir.
- `PATCH` submission requests carry no `unassignOnGrade` (Teacher-API
  precision), and each state change is individually verified via
  `GET file` + `revokePermissions` bookkeeping in the attachment mimic of V5.

## 5. Not covered (honest gaps)

- No live Google Classroom round-trip is possible from CI; the documented
  V5 notes were cross-checked during inspection instead of being re-derived.
- Frontend Classroom panels are part of the Phase 5 UI work, so no frontend
  Classroom tests exist in this phase.
- Rate-limit / retry jitter paths are unit-simulated only (`FakeClassroomClient`
  has deterministic responses); real exponential backoff against Google is
  not load-tested.
