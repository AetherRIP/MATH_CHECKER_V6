/* Storage: real measurements of the application's own data directory.
 *
 * Numbers come from the bounded /api/storage/summary walk computed on request
 * — nothing is scanned in the background and nothing is fabricated. No
 * deletion or migration actions exist yet.
 */

import { html, render as toHTML } from "../ui/html.js";
import { pageHeader, card, statCard } from "../ui/card.js";
import { button } from "../ui/button.js";
import { badge } from "../ui/badge.js";
import { dataTable } from "../ui/table.js";
import { emptyState, errorState, loadingState } from "../ui/states.js";
import { api } from "../api.js";
import { formatBytes, formatCount } from "../format.js";

function summaryHTML(summary) {
  const categoriesWithData = summary.categories.filter(
    (category) => category.files > 0 || category.bytes > 0,
  ).length;

  return html`
    <div class="stat-grid">
      ${statCard({
        iconName: "storage",
        label: "Total stored",
        value: formatBytes(summary.total.bytes),
        hint: "Across the application data directory",
      })}
      ${statCard({
        iconName: "file",
        label: "Files",
        value: formatCount(summary.total.files),
        hint: "Counted on request",
        tone: "info",
      })}
      ${statCard({
        iconName: "tasks",
        label: "Categories in use",
        value: `${categoriesWithData} of ${summary.categories.length}`,
        hint: "Storage categories containing data",
        tone: "success",
      })}
    </div>

    ${summary.truncated
      ? html`<p class="field__note">${badge({ label: "Truncated", tone: "warning" })}<span>The scan stopped at its safety limit; figures are a lower bound.</span></p>`
      : ""}

    <div class="mt-4">
      ${dataTable({
        caption: "Measurements cover the application data directory only and are computed when this page is opened or refreshed.",
        columns: [
          { key: "category", label: "Category" },
          { key: "files", label: "Files", numeric: true },
          { key: "size", label: "Size", numeric: true },
          { key: "description", label: "Description" },
        ],
        rows: summary.categories.map((category) => ({
          key: category.id,
          cells: {
            category: category.label,
            files: formatCount(category.files),
            size: formatBytes(category.bytes),
            description: category.description,
          },
        })),
      })}
    </div>

    ${summary.total.files === 0
      ? html`<div class="mt-5">
          ${emptyState({
            iconName: "storage",
            title: "No stored data yet",
            description:
              "Files and reports appear here as they are created by later phases. The application has not stored anything so far.",
          })}
        </div>`
      : ""}
  `;
}

async function load(root) {
  const section = root.querySelector('[data-section="storage"]');
  if (section) section.innerHTML = toHTML(loadingState({ label: "Measuring application storage…" }));
  try {
    const summary = await api.storageSummary();
    if (section) section.innerHTML = toHTML(summaryHTML(summary));
  } catch (err) {
    if (section) {
      section.innerHTML = toHTML(
        errorState({
          title: "Storage summary unavailable",
          description: "The application server could not be reached to measure storage.",
          actions: button({ label: "Retry", iconName: "refresh", attrs: 'data-action="retry"' }),
        }),
      );
    }
  }
}

export function render() {
  return html`
    ${pageHeader({
      title: "Storage",
      description:
        "Local application data and files. Measurements are real and computed on request — nothing is scanned in the background.",
      actions: button({ label: "Refresh", iconName: "refresh", attrs: 'data-action="retry"' }),
    })}
    ${card({
      title: "Storage overview",
      body: html`<div data-section="storage">${loadingState({ label: "Measuring application storage…" })}</div>`,
    })}
  `;
}

export function mount(root) {
  load(root);
  root.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof Element && target.closest('[data-action="retry"]')) {
      load(root);
    }
  });
}
