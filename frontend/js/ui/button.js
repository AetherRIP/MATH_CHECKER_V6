/* Buttons: solid, secondary and ghost variants, as links when `href` is
 * given. Disabled buttons may carry a visible note that explains why the
 * action is unavailable — never a dead, unexplained control. */

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
