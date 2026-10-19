/* Buttons and icon buttons. Disabled buttons may carry a visible note that
 * explains why the action is unavailable — never a dead, unexplained control. */

import { html, raw } from "./html.js";
import { icon } from "../icons.js";

export function button({
  label,
  variant = "secondary",
  iconName,
  href,
  disabled = false,
  note,
  attrs = "",
  type = "button",
} = {}) {
  const content = html`${iconName ? icon(iconName, { size: 16 }) : ""}<span>${label}</span>`;
  const cls = `btn btn--${variant}`;
  let control;
  if (href && !disabled) {
    control = html`<a class="${cls}" href="${href}" ${raw(attrs)}>${content}</a>`;
  } else {
    control = html`<button type="${type}" class="${cls}" ${raw(attrs)}${disabled ? " disabled" : ""} aria-disabled="${disabled ? "true" : "false"}">${content}</button>`;
  }
  if (!note) return control;
  return html`<div class="btn-wrap">${control}<p class="btn-note">${note}</p></div>`;
}

export function iconButton({ name, label, attrs = "", variant = "icon", size = 18 } = {}) {
  return html`<button type="button" class="btn btn--${variant}" aria-label="${label}" title="${label}" ${raw(attrs)}>${icon(name, { size })}</button>`;
}

export function linkButton({ label, href, iconName, variant = "secondary", attrs = "" } = {}) {
  return html`<a class="btn btn--${variant}" href="${href}" ${raw(attrs)}>${iconName ? icon(iconName, { size: 16 }) : ""}<span>${label}</span></a>`;
}
