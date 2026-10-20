/* Status badges: small labelled pills with optional tone and icon. */

import { html } from "./html.js";
import { icon } from "../icons.js";

export function badge({ label, tone = "neutral", iconName } = {}) {
  return html`<span class="badge" data-tone="${tone}">${iconName ? icon(iconName, { size: 12 }) : ""}${label}</span>`;
}
