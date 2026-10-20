# CLASSROOM_CONFIGURATION.md — setup, permissions, credential safety

Companions: [CLASSROOM_MIGRATION.md](CLASSROOM_MIGRATION.md),
[CLASSROOM_TEST_REPORT.md](CLASSROOM_TEST_REPORT.md).

## 1. Required configuration

| Setting | Requirement | Where |
|---|---|---|
| Google OAuth client JSON | An `installed` (or `web`) `client_secret` file containing `client_id` + `client_secret` | `<data_dir>/secrets/google_oauth_client.json` |
| `MC6_GOOGLE_OAUTH_CLIENT` | OPTIONAL override: a path to that JSON, or inline JSON (`{"installed":{…}}`), which is materialised under the data directory | environment or `.env` |
| Google account | A teacher account with Classroom access; courses must be ACTIVE | connect flow |
| Correction engine (`MC6_AI_API_KEY`) | Required for the correction step itself (unchanged Phase 3 setting) | environment |

There is no service-account mode: Classroom grade/attachment write-back
requires the classroom teacher's own user context; a service account cannot
legitimately perform those operations against real students.

## 2. OAuth scopes (identical to V5)

```
classroom.courses.readonly
classroom.coursework.students
classroom.rosters.readonly
drive.file          (report upload — narrowest possible)
drive.readonly      (reading student submissions)
openid + userinfo.email (which account is connected)
```

## 3. Connect flow

1. Place the client JSON in the data directory (`secrets/google_oauth_client.json`).
2. `POST /api/classroom/connect?open_browser=true` (or the equivalent UI action).
3. A loopback browser flow uses `access_type=offline & prompt=consent` so a
   refresh token is actually issued — the V5 lesson: skipping this yields a
   "successful" sign-in with no refresh token.
4. The refresh token is stored at
   `<data_dir>/secrets/classroom_refresh_token` (inside the git-ignored
   `data/` tree, `chmod 600` where the OS honours it) together with
   `classroom_refresh_token.scopes` (the granted scope set).

Silent refresh gives access tokens afterwards. If Google answers
`invalid_scope` on refresh, the app reports **reconnect required for the
drive.file permission** — a deliberate distinction from expiry.

## 4. Credential safety rules (enforced)

- The refresh token never appears in logs, API responses, or documentation.
- Inline JSON clients are materialised to `data/secrets/…` and never echoed.
- `.gitignore` already excludes `data/` (covers `data/secrets/**`).
- `/api/classroom/status` returns only `{configured, connected, email,
  problem, publish_allowed}` — no token material.
- Disconnect clears both the refresh token and the recorded scope set.

## 5. Permissions reality (documented, not invented)

- **Grades/returns** only succeed for coursework created by the SAME Google
  Cloud project as this app. Teacher-made coursework → HTTP 403
  `ProjectPermissionDenied` → V6 records `not_supported` with a clear message.
- **Attachments** obey the same ownership rule plus per-file ownership
  (this app must own the Drive file).
- **Report generation** is always available; upload/grade/return are gated by
  the above and each records its own verified status.

## 6. Manual setup checklist for a live deployment

1. Create/select a Google Cloud project; enable the Google Classroom API and
   the Drive API.
2. Create an OAuth consent screen (Internal or External-with-test-users as
   appropriate) requesting the scopes in §2.
3. Create an OAuth client of type "Desktop app" and download its
   `client_secret` JSON.
4. Place the JSON at `<data_dir>/secrets/google_oauth_client.json`.
5. Start V6 and complete `/api/classroom/connect`.
6. (Optional) Set `MC6_GOOGLE_OAUTH_CLIENT` instead for path/inline config.
