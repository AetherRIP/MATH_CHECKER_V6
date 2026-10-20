/* Consistent empty / error / loading state panels used across all pages. */

import { html } from "./html.js";
import { icon } from "../icons.js";

export function emptyState({
  iconName = "info",
  title,
  description,
  actions,
  tone = "neutral",
  compact = false,
} = {}) {
  return html`
    <div class="state-panel${compact ? " state-panel--compact" : ""}" data-tone="${tone}">
      <span class="state-panel__icon">${icon(iconName, { size: 20 })}</span>
      <p class="state-panel__title">${title}</p>
      ${description ? html`<p class="state-panel__desc">${description}</p>` : ""}
      ${actions ? html`<div class="state-panel__actions">${actions}</div>` : ""}
    </div>
  `;
}

export function errorState({ title = "Something went wrong", description, actions } = {}) {
  return emptyState({ iconName: "alert", title, description, actions, tone: "error" });
}

export function loadingState({ label = "Loading…" } = {}) {
  return html`
    <div class="state-panel state-panel--compact" role="status">
      <span class="spinner" aria-hidden="true"></span>
      <p class="state-panel__desc">${label}</p>
    </div>
  `;
}
