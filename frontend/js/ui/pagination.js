/* Minimal pagination for paged lists (used by the submission review list).
 * Buttons carry data-page attributes; the owning page handles the clicks. */

import { html } from "./html.js";
import { icon } from "../icons.js";

export function paginationTemplate({ page, pageSize, total, label = "Pagination" } = {}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(Math.max(1, page), pages);
  const first = total === 0 ? 0 : (current - 1) * pageSize + 1;
  const last = Math.min(total, current * pageSize);
  return html`
    <nav class="pagination" aria-label="${label}">
      <button
        type="button"
        class="btn btn--secondary btn--icon"
        data-page="${current - 1}"
        aria-label="Previous page"
        title="Previous page"
        ${current <= 1 ? "disabled" : ""}
      >${icon("chevron-left", { size: 15 })}</button>
      <span>Page ${current} of ${pages}</span>
      <button
        type="button"
        class="btn btn--secondary btn--icon"
        data-page="${current + 1}"
        aria-label="Next page"
        title="Next page"
        ${current >= pages ? "disabled" : ""}
      >${icon("chevron-right", { size: 15 })}</button>
      <span class="pagination__spacer">${first}–${last} of ${total}</span>
    </nav>
  `;
}
