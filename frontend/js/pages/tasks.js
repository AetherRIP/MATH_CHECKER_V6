/* Task Manager: the future home of background-work visibility.
 *
 * The planned task categories are shown with honest empty states. No queue,
 * worker or progress is simulated — the task system itself arrives in a
 * later phase.
 */

import { html } from "../ui/html.js";
import { icon } from "../icons.js";
import { pageHeader, card } from "../ui/card.js";
import { badge } from "../ui/badge.js";
import { emptyState } from "../ui/states.js";

const CATEGORIES = [
  {
    iconName: "correction",
    title: "Assignment correction tasks",
    description: "Homework correction jobs, from upload through marking to completion.",
    live: true,
  },
  {
    iconName: "file",
    title: "PDF processing tasks",
    description: "Standard and large PDF extraction jobs for submissions and mark schemes.",
    live: false,
  },
  {
    iconName: "plug",
    title: "Network and integration tasks",
    description: "Google Classroom synchronisation and other external service work.",
    live: false,
  },
  {
    iconName: "settings",
    title: "General application tasks",
    description: "Report generation, exports and maintenance work.",
    live: false,
  },
];

export function render() {
  return html`
    ${pageHeader({
      eyebrow: "Background work",
      title: "Task Manager",
      description:
        "Correction jobs are tracked on the AI Correction page, including queued, processing, completed and failed states. Other task categories remain planned.",
      actions: badge({ label: "Live status on AI Correction", tone: "info", iconName: "clock" }),
    })}
    <div class="grid-2">
      ${CATEGORIES.map(
        (category) => html`
          <section class="card">
            <header class="card__header">
              <div>
                <h2 class="card__title">${category.title}</h2>
                <p class="card__desc">${category.description}</p>
              </div>
              <span class="stat-card__icon">${icon(category.iconName, { size: 18 })}</span>
            </header>
            ${emptyState({
              iconName: "tasks",
              title: "No tasks",
              description: "Tasks in this category will be listed here as they are created.",
              compact: true,
            })}
            <div class="task-card__state">
              ${category.live
                ? badge({ label: "See AI Correction", tone: "info" })
                : badge({ label: "Planned · later phase", tone: "neutral" })}
              <span>${category.live ? "Open the AI Correction page for live correction-job status." : "This category becomes active in a later phase."}</span>
            </div>
          </section>
        `,
      )}
    </div>
  `;
}
