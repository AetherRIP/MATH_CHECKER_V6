# Math Checker V6 — Phase 1

A lightweight, modular application for correcting Edexcel IGCSE Mathematics
homework with AI, generating reports, and (in later phases) integrating with
Google Classroom.

**Phase 1 delivers the foundation:** a polished dark-themed interface, shared
application shell, reusable components, and five working pages — with clearly
marked integration points for the correction engine that arrives in Phase 2.

The application runs and is fully useful **without any AI key or credential**.

---

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+ · FastAPI · uvicorn (2 runtime dependencies) |
| Frontend | Vanilla HTML/CSS/ES modules — **no build step, no Node toolchain needed to run** |
| Routing | Hash routes (`/#/dashboard`) — every page is directly navigable |
| Storage | None in Phase 1 (no database); runtime data directory only |

## Requirements

- Python 3.11 or newer (developed and tested on 3.14)
- Node.js 20+ **only if you want to run the frontend unit tests** — not needed to run the app

## Setup

```bash
cd MATH_CHECKER_V6
python -m venv .venv

# Windows (Git Bash / PowerShell):
.venv/Scripts/python -m pip install -r requirements-dev.txt
# macOS / Linux:
#   .venv/bin/python -m pip install -r requirements-dev.txt
```

Use `requirements-dev.txt` for development (it includes the test tools).
For a deployment that only needs to run, `requirements.txt` is enough:

```bash
.venv/Scripts/python -m pip install -r requirements.txt
```

## Launch

```bash
.venv/Scripts/python main.py
```

Then open **http://127.0.0.1:8643** in a browser.

Options:

```bash
python main.py --port 9000       # override the port
python main.py --host 0.0.0.0    # listen on all interfaces (explicit opt-in)
python main.py --version         # print the version and exit
```

Configuration is environment-driven (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `MC6_HOST` | `127.0.0.1` | interface to bind (private by default) |
| `MC6_PORT` | `8643` | TCP port |
| `MC6_DEBUG` | `0` | `1` enables verbose logging |
| `MC6_LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` |
| `MC6_DATA_DIR` | `./data` | application data directory |
| `MC6_TMP_DIR` | `<data>/tmp` | temporary processing directory |

To use a `.env` file, copy the template:

```bash
cp .env.example .env   # then edit; real values never belong in .env.example
```

Values already present in the process environment always win over `.env`.

## Testing

Backend (pytest):

```bash
.venv/Scripts/python -m pytest backend/tests -q
```

Frontend (Node's built-in test runner — zero packages to install):

```bash
cd frontend && npm test
# equivalent: node --test "tests/*.test.mjs"
```

## Project structure

```
MATH_CHECKER_V6/
├── main.py                  # launcher: config → uvicorn
├── requirements.txt         # 2 runtime dependencies
├── requirements-dev.txt     # + pytest, httpx
├── .env.example             # configuration template (placeholders only)
├── backend/
│   ├── app/
│   │   ├── config.py        # MC6_* env vars + minimal .env loader
│   │   ├── main.py          # FastAPI app, static serving, error handling
│   │   └── api/
│   │       ├── system.py    # /api/health, /api/system/status
│   │       └── storage.py   # /api/storage/summary
│   └── tests/               # pytest suite
├── frontend/
│   ├── index.html           # app shell document
│   ├── css/                 # tokens.css → base/layout/components
│   ├── js/
│   │   ├── main.js          # bootstrap
│   │   ├── router.js        # hash router (pages load on demand)
│   │   ├── api.js           # service layer — the future integration seam
│   │   ├── store.js         # UI preferences (localStorage, harmless data only)
│   │   ├── ui/              # reusable components
│   │   ├── layout/shell.js  # sidebar + top bar + content slot
│   │   └── pages/           # dashboard, correction, settings, storage, tasks, notfound
│   └── tests/               # node --test suite
└── docs/
    ├── architecture.md      # design decisions and extension points
    ├── phase-1-report.md    # implementation report and measurements
    └── screenshots/         # verified UI captures
```

## What works in Phase 1

- Complete application shell: collapsible sidebar, top bar, mobile drawer
- Five pages + a deliberate not-found page, all directly navigable
- AI Correction workspace: client-side file selection with validation
  (PDF/PNG/JPG, 25 MB limit), review/remove with confirmation dialog,
  assignment and options draft
- Settings: interface preferences that really persist (start page, density,
  confirmation behaviour); future configuration sections are clearly marked
  placeholders that collect nothing
- Storage: real, on-request measurements of the application data directory
- Task Manager: the planned task categories with honest empty states
- Consistent empty/loading/error states, toasts, modals, tabs, tables

## What is deliberately NOT in Phase 1

AI correction logic · Gemini/other provider integration · PDF extraction ·
mark-scheme verification · grading · Google Classroom sync · report
generation · background workers · authentication · database · deployment
automation. The UI marks each of these as planned; nothing pretends to work.

## Troubleshooting

**`python main.py` says "Configuration error: MC6_PORT must be an integer"**
A `.env` file or environment variable sets `MC6_PORT` to a non-numeric value.
Fix or remove it.

**Port 8643 is already in use**
Another application (perhaps a previous instance) holds the port. Start on
another one: `python main.py --port 8650`.

**"No AI provider is configured" note at startup**
Normal for Phase 1 — the whole interface works without one.

**The page loads but looks like an older version**
The frontend is served as plain files; do a hard refresh (Ctrl+Shift+R) after
replacing files so the browser drops cached modules.

**Frontend tests fail to start with "Cannot find module"**
Run them via the documented command (`npm test` inside `frontend/`) — on some
Windows shells `node --test tests/` (directory form) is not resolved; the glob
form used by the script works everywhere tested.

**Where are my files stored?**
Runtime data lives under `data/` (or `MC6_DATA_DIR`), created automatically on
first start. Phase 1 writes no user data; the directory is created empty.

## License

See the repository's license file.
