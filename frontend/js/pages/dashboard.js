/* Dashboard: an honest overview of the correction system.
 *
 * Counts come from the local database and readiness comes from the server.
 * Nothing here is sample data; loading, empty and error states are real.
 */

import { html, render as toHTML } from "../ui/html.js";
import { pageHeader, card, statCard, detailRows } from "../ui/card.js";
import { button } from "../ui/button.js";
import { badge } from "../ui/badge.js";
import { dataTable } from "../ui/table.js";
import { emptyState, errorState, loadingState } from "../ui/states.js";
import { api } from "../api.js";
import { formatCount } from "../format.js";

const INTEGRATION_SOURCES = 2;

export function readinessRows(status) {
  const database = status.database || {};
  const databaseReady = database.status === "ready";
  return [
    {
      label: "Application interface",
      value: badge({ label: "Ready", tone: "success", iconName: "check-circle" }),
    },
    {
      label: "Backend API",
      value: badge({ label: "Reachable", tone: "success", iconName: "check-circle" }),
    },
    {
      label: "Database",
      value: databaseReady
        ? badge({
            label: `Ready · schema ${database.schema_version}`,
            tone: "success",
            iconName: "check-circle",
          })
        : badge({ label: "Unavailable", tone: "error" }),
    },
    {
      label: "AI provider",
      value: status.ai_provider_configured
        ? badge({ label: "Configured", tone: "success" })
        : badge({ label: "Not configured (optional)", tone: "neutral" }),
    },
    {
      label: "Google Classroom",
      value: status.classroom_configured
        ? badge({ label: "Configured", tone: "success" })
        : badge({ label: "Not configured (planned)", tone: "neutral" }),
    },
    {
      label: "Correction processing",
      value: badge({ label: "Planned · Phase 3", tone: "warning" }),
    },
    {
      label: "Background tasks",
      value: badge({ label: "Planned · later phase", tone: "warning" }),
    },
  ];
}

export function submissionStatusRows(counts) {
  return [
    { key: "missing", label: "Missing", count: counts.missing },
    { key: "draft", label: "Draft", count: counts.draft },
    { key: "submitted", label: "Submitted", count: counts.submitted },
    { key: "graded", label: "Graded", count: counts.graded },
    { key: "failed", label: "Failed", count: counts.failed },
  ];
}

export function statsHTML(counts) {
  if (!counts || counts.total === 0) {
    return emptyState({
      iconName: "storage",
      title: "No submissions recorded yet",
      description:
        "Students, assignments and submissions appear here as they are added to the local database.",
      compact: true,
    });
  }

  return dataTable({
    caption: "Counts are read from the local database when this page opens.",
    columns: [
      { key: "status", label: "Status" },
      { key: "count", label: "Submissions", numeric: true },
    ],
    rows: submissionStatusRows(counts).map((row) => ({
      key: row.key,
      cells: { status: row.label, count: formatCount(row.count) },
    })),
  });
}

export function render() {
  return html`
    ${pageHeader({
      title: "Dashboard",
      description:
        "A quick overview of the correction system. Counts and readiness are read from the running backend.",
      actions: html`
        ${button({ label: "New correction", variant: "primary", iconName: "correction", href: "#/correction" })}
        ${button({ label: "Settings", iconName: "settings", href: "#/settings" })}
      `,
    })}

    <section aria-labelledby="stats-heading">
      <h2 id="stats-heading" class="sr-only">Key figures</h2>
      <div class="stat-grid">
        ${statCard({
          iconName: "tasks",
          label: "Students",
          value: html`<span data-fill="stat-students">—</span>`,
          hint: "Stored in the local database",
        })}
        ${statCard({
          iconName: "file",
          label: "Assignments",
          value: html`<span data-fill="stat-assignments">—</span>`,
          hint: "Including chapter and lesson codes",
          tone: "info",
        })}
        ${statCard({
          iconName: "storage",
          label: "Submissions",
          value: html`<span data-fill="stat-submissions">—</span>`,
          hint: html`<span data-fill="stat-submissions-hint">Loading…</span>`,
          tone: "success",
        })}
        ${statCard({
          iconName: "plug",
          label: "Integrations configured",
          value: html`<span data-fill="integrations">—</span>`,
          hint: "AI provider and Google Classroom",
          tone: "warning",
        })}
      </div>
    </section>

    <div class="stack">
      ${card({
        title: "Submissions by status",
        description: "Live counts of student work recorded in the local database.",
        actions: button({ label: "Refresh", iconName: "refresh", attrs: 'data-action="retry-stats"' }),
        body: html`<div data-section="stats">${loadingState({ label: "Reading database statistics…" })}</div>`,
      })}

      ${card({
        title: "Recent correction jobs",
        description: "The latest homework correction jobs and their states.",
        body: dataTable({
          columns: [
            { key: "job", label: "Job" },
            { key: "assignment", label: "Assignment" },
            { key: "status", label: "Status" },
            { key: "started", label: "Started" },
          ],
          rows: [],
          empty: {
            iconName: "tasks",
            title: "No correction jobs yet",
            description:
              "Correction jobs appear here once the AI correction engine is available in Phase 3.",
          },
        }),
      })}

      <div class="grid-2">
        ${card({
          title: "Recent activity",
          description: "Actions taken in the application.",
          body: emptyState({
            iconName: "clock",
            title: "No activity yet",
            description:
              "Corrections, reports and other actions will appear here as you use the application.",
            compact: true,
          }),
        })}
        ${card({
          title: "Quick actions",
          description: "Jump straight to a workspace.",
          body: html`
            <div class="row">
              ${button({ label: "New correction", variant: "primary", iconName: "correction", href: "#/correction" })}
              ${button({ label: "Manage storage", iconName: "storage", href: "#/storage" })}
              ${button({ label: "Task manager", iconName: "tasks", href: "#/tasks" })}
            </div>
          `,
        })}
      </div>

      ${card({
        title: "Application readiness",
        description: "Live status of the application and its planned integrations.",
        body: html`
          <div data-section="readiness">${loadingState({ label: "Reading application status…" })}</div>
          <p class="field__help mt-4">
            Status is read from the server when this page opens. Nothing on this page is sample data.
          </p>
        `,
      })}
    </div>
  `;
}

function setText(root, selector, value) {
  const element = root.querySelector(selector);
  if (element) element.textContent = value;
}

async function loadStats(root) {
  const section = root.querySelector('[data-section="stats"]');
  if (section) section.innerHTML = toHTML(loadingState({ label: "Reading database statistics…" }));

  try {
    const data = await api.databaseStats();
    const counts = data.counts;
    setText(root, '[data-fill="stat-students"]', formatCount(counts.students));
    setText(root, '[data-fill="stat-assignments"]', formatCount(counts.assignments));
    setText(root, '[data-fill="stat-submissions"]', formatCount(counts.submissions.total));
    setText(
      root,
      '[data-fill="stat-submissions-hint"]',
      `${counts.submissions.missing} missing · ${counts.submissions.draft} drafts · ${counts.submissions.graded} graded`,
    );
    if (section) section.innerHTML = toHTML(statsHTML(counts.submissions));
  } catch (err) {
    for (const selector of ['[data-fill="stat-students"]', '[data-fill="stat-assignments"]', '[data-fill="stat-submissions"]']) {
      setText(root, selector, "—");
    }
    setText(root, '[data-fill="stat-submissions-hint"]', "Statistics unavailable");
    if (section) {
      section.innerHTML = toHTML(
        errorState({
          title: "Database statistics unavailable",
          description: "The application server could not be reached to read the local database.",
          actions: button({ label: "Retry", iconName: "refresh", attrs: 'data-action="retry-stats"' }),
        }),
      );
    }
  }
}

async function loadReadiness(root) {
  const section = root.querySelector('[data-section="readiness"]');
  const fill = root.querySelector('[data-fill="integrations"]');
  try {
    const status = await api.systemStatus();
    const configured =
      (status.ai_provider_configured ? 1 : 0) + (status.classroom_configured ? 1 : 0);
    if (fill) fill.textContent = `${configured} of ${INTEGRATION_SOURCES}`;
    if (section) section.innerHTML = toHTML(detailRows(readinessRows(status)));
  } catch (err) {
    if (fill) fill.textContent = "—";
    if (section) {
      section.innerHTML = toHTML(
        errorState({
          title: "Status unavailable",
          description: "The application server could not be reached to read the current status.",
          actions: button({ label: "Retry", iconName: "refresh", attrs: 'data-action="retry-status"' }),
        }),
      );
    }
  }
}

export function mount(root, { signal } = {}) {
  loadStats(root);
  loadReadiness(root);
  root.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest('[data-action="retry-stats"]')) {
      loadStats(root);
    }
    if (target.closest('[data-action="retry-status"]')) {
      loadReadiness(root);
    }
  }, { signal });
}
