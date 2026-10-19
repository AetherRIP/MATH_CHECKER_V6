/* Dashboard: an honest overview of the correction system.
 *
 * All counts are real (zero until correction jobs exist in later phases) and
 * readiness rows are read live from the server. Nothing here is sample data.
 */

import { html, render as toHTML } from "../ui/html.js";
import { pageHeader, card, statCard, detailRows } from "../ui/card.js";
import { button } from "../ui/button.js";
import { badge } from "../ui/badge.js";
import { dataTable } from "../ui/table.js";
import { emptyState, errorState, loadingState } from "../ui/states.js";
import { api } from "../api.js";

const INTEGRATION_SOURCES = 2;

function readinessRows(status) {
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
      value: badge({ label: "Planned · Phase 2", tone: "warning" }),
    },
    {
      label: "Background tasks",
      value: badge({ label: "Planned · later phase", tone: "warning" }),
    },
  ];
}

export function render() {
  return html`
    ${pageHeader({
      title: "Dashboard",
      description:
        "A quick overview of the correction system. Phase 1 lays the foundation — correction data appears here once jobs can run in Phase 2.",
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
          label: "Correction jobs",
          value: "0",
          hint: "No correction jobs yet",
        })}
        ${statCard({
          iconName: "file",
          label: "Submissions processed",
          value: "0",
          hint: "Nothing processed yet",
          tone: "info",
        })}
        ${statCard({
          iconName: "storage",
          label: "Reports generated",
          value: "0",
          hint: "No reports yet",
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
              "Correction jobs appear here once the AI correction engine is available in Phase 2.",
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

export function mount(root) {
  loadReadiness(root);
  root.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof Element && target.closest('[data-action="retry-status"]')) {
      loadReadiness(root);
    }
  });
}
