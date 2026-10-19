/* Task Manager: the future home of background-work visibility.
 *
 * Phase 1 shows the planned task categories with honest empty states. No
 * queue, worker or progress is simulated — the task system itself arrives in
 * a later phase.
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
  },
  {
    iconName: "file",
    title: "PDF processing tasks",
    description: "Standard and large PDF extraction jobs for submissions and mark schemes.",
  },
  {
    iconName: "plug",
    title: "Network and integration tasks",
    description: "Google Classroom synchronisation and other external service work.",
  },
  {
    iconName: "settings",
    title: "General application tasks",
    description: "Report generation, exports and maintenance work.",
  },
];

export function render() {
  return html`
    ${pageHeader({
      title: "Task Manager",
      description:
        "Visibility for background work once it exists. Later phases add task states, retries, logs and cancellation here — no task system runs in Phase 1.",
      actions: badge({ label: "Task processing planned", tone: "warning", iconName: "clock" }),
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
              ${badge({ label: "Empty", tone: "neutral" })}
              <span>Task processing arrives in a later phase.</span>
            </div>
          </section>
        `,
      )}
    </div>
  `;
}
