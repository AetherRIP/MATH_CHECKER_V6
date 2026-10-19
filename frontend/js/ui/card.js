/* Content cards, statistic cards and the standard page header. */

import { html } from "./html.js";
import { icon } from "../icons.js";

export function pageHeader({ title, description, actions } = {}) {
  return html`
    <header class="page-header">
      <div class="page-header__text">
        <h1>${title}</h1>
        ${description ? html`<p class="page-header__desc">${description}</p>` : ""}
      </div>
      ${actions ? html`<div class="page-header__actions">${actions}</div>` : ""}
    </header>
  `;
}

export function card({ title, description, actions, body, footer, className = "" } = {}) {
  return html`
    <section class="card ${className}">
      ${title || actions
        ? html`<header class="card__header">
            <div>
              ${title ? html`<h2 class="card__title">${title}</h2>` : ""}
              ${description ? html`<p class="card__desc">${description}</p>` : ""}
            </div>
            ${actions ? html`<div class="card__actions">${actions}</div>` : ""}
          </header>`
        : ""}
      <div class="card__body">${body}</div>
      ${footer ? html`<footer class="card__footer">${footer}</footer>` : ""}
    </section>
  `;
}

export function statCard({ iconName, label, value, hint, tone = "accent" } = {}) {
  return html`
    <div class="stat-card" data-tone="${tone}">
      <div class="stat-card__top">
        <span class="stat-card__icon">${icon(iconName, { size: 18 })}</span>
        <span class="stat-card__label">${label}</span>
      </div>
      <div class="stat-card__value">${value}</div>
      ${hint ? html`<div class="stat-card__hint">${hint}</div>` : ""}
    </div>
  `;
}

export function detailRows(rows) {
  return html`<div class="detail-rows">${rows.map(
    (row) => html`<div class="detail-row">
      <span class="detail-row__label">${row.label}</span>
      <span class="detail-row__value">${row.value}</span>
    </div>`,
  )}</div>`;
}
