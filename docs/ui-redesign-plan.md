# Math Checker V6 — UI Redesign Record (UI/UX layer only)

Date: 2026-10-19 · Scope: frontend visual/structural redesign. No backend, API,
schema, engine or roadmap changes.

## Audit findings (why the old UI was rejected)
- The shell was a generic SaaS admin template: full-height left sidebar plus a
  breadcrumb top bar, visually continuous with Math Checker V5.
- Every page shared one composition — a page header over a stack of identical
  rounded cards — so Dashboard, Storage and Settings were interchangeable.
- AI Correction was a five-tab wizard that hid job state, results, engine
  status and upload limits behind separate tabs.
- Stat tiles were uniform icon chips with no information hierarchy.

## What changed structurally

| Element | Before | After |
|---|---|---|
| Shell | Global sidebar + breadcrumb bar | Sticky **command bar**: brand, segmented nav pills (active = turquoise), server-status cluster; content canvas below; per-page context rail on Correction |
| Dashboard | 4 equal stat tiles + card stack | **Pipeline strip** (Queued / Processing / Completed / Failed live counters, derived from the real job list) as the focal readout, then submissions table, readiness panel, quick actions |
| AI Correction | 5-tab wizard only | **Console layout**: left "How a correction runs" workflow rail + workflow tabs; active job card now shows a **stage track** (Validated → Queued → Marking → Results); results page leads with Marks / Percentage / Review-required readout tiles |
| Storage | Generic cards + table | **Quota ledger**: per-category measurement bars plus the measurement table |
| Task Manager | 4 uniform cards | Category cards with honest per-category state ("See AI Correction" vs "Planned · later phase") |
| Settings | Flat card stack | **Two-pane**: category rail (Server, General, Appearance, AI provider, Classroom, Storage, Application info) linking to detail panes |
| Not found | Generic panel | Console error panel with eyebrow label |
| Foundations | Old tokens/skins | New near-black navy tokens, tighter radii, small-caps labels, tabular numerals, ledgers, meters, stage tracks, quieter shadows |

## Functionality preserved
- All routes, API calls (`api.js` seam), upload validation, idempotent
  submission, polling, report rendering, preference persistence, modals,
  toasts, keyboard focus management and ARIA semantics are unchanged.
- All test-pinned hooks kept: `role="tablist"`, `data-section`, `data-fill`,
  `aria-current`, one `<h1>` per page, honest empty states, no fabricated data.
- Backend untouched: 185 tests still pass; frontend suite updated where it
  asserted removed structure only (collapse-sidebar button, dashboard card
  title) and extended with pipeline-counter tests — 49 pass.

## Files changed
- `frontend/css/tokens.css`, `base.css`, `layout.css`, `components.css` — new design system.
- `frontend/js/layout/shell.js` — command-bar shell.
- `frontend/js/ui/card.js` — eyebrow page header, accent stat readouts.
- `frontend/js/pages/dashboard.js` — pipeline console (+ `pipelineHTML`, `pipelineCounts` exports).
- `frontend/js/pages/correction.js` — console layout, stage track, results tiles.
- `frontend/js/pages/storage.js` — quota ledger.
- `frontend/js/pages/tasks.js` — per-category state.
- `frontend/js/pages/settings.js` — two-pane layout.
- `frontend/js/pages/notfound.js` — console error panel.
- `frontend/tests/pages.test.mjs` — assertions updated for removed structure; new pipeline tests.

## Verification performed
- `npm test` (frontend): **49 passed**, 0 failed, exit 0.
- `pytest backend/tests`: **185 passed**, exit 0.
- Browser inspection at 1280×900 and 760×900 on all pages: no horizontal
  overflow, no console errors, active nav pills render, drawers/menus behave.
- Screenshots captured (since removed with the verification workspace):
  dashboard/correction/storage/tasks/settings at desktop width, dashboard at
  760px.

## Remaining limitations
- Manual/Classroom review pages and report exports remain honest "planned"
  states — they depend on later phases, as required by the scope boundary.
- Reduced-motion is honoured via the existing media query; no other animation
  was added beyond the processing-stage pulse (which is disabled under
  reduced motion).
