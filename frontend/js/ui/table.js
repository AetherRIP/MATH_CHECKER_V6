/* Data table. On narrow screens rows stack into labelled cards (CSS driven);
 * on wide screens it is a normal table. An empty row set renders the shared
 * empty-state panel instead of a bare grid. */

import { html } from "./html.js";
import { emptyState } from "./states.js";

export function dataTable({ columns, rows = [], empty, caption } = {}) {
  return html`
    <div class="table-wrap">
      <table class="table">
        ${caption ? html`<caption>${caption}</caption>` : ""}
        <thead>
          <tr>${columns.map((col) => html`<th scope="col">${col.label}</th>`)}</tr>
        </thead>
        <tbody>
          ${rows.length
            ? rows.map(
                (row) => html`<tr>${columns.map(
                  (col) => html`<td data-label="${col.label}" class="${col.numeric ? "is-num" : ""}">${row.cells[col.key]}</td>`,
                )}</tr>`,
              )
            : html`<tr class="table__empty">
                <td colspan="${columns.length}">
                  ${empty ? emptyState({ compact: true, ...empty }) : ""}
                </td>
              </tr>`}
        </tbody>
      </table>
    </div>
  `;
}
