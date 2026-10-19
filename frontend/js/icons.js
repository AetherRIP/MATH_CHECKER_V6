/* Locally bundled SVG icons (24×24, stroke style). No icon CDN is used. */

import { raw } from "./ui/html.js";

const ICONS = {
  dashboard:
    '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
  correction:
    '<path d="M12 3.5l7.5 3v5c0 4.6-3.1 7.8-7.5 9-4.4-1.2-7.5-4.4-7.5-9v-5z"/><path d="M9 11.7l2.2 2.2 4-4.4"/>',
  storage:
    '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v13c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-13"/><path d="M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8"/>',
  tasks:
    '<path d="M4 7l1.8 1.8L9 5.4"/><path d="M4 17.2l1.8 1.8L9 15.6"/><path d="M12 7.4h8"/><path d="M12 17.6h8"/>',
  settings:
    '<path d="M4 8h9"/><path d="M17.5 8H20"/><path d="M4 16h3.5"/><path d="M12 16h8"/><circle cx="15.2" cy="8" r="2.2"/><circle cx="9.7" cy="16" r="2.2"/>',
  menu: '<path d="M4 6.5h16"/><path d="M4 12h16"/><path d="M4 17.5h16"/>',
  "chevron-left": '<path d="M14.5 6l-6 6 6 6"/>',
  "chevron-right": '<path d="M9.5 6l6 6-6 6"/>',
  "panel-collapse":
    '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M9.5 4.5v15"/><path d="M15.5 9.5L13 12l2.5 2.5"/>',
  x: '<path d="M6.5 6.5l11 11"/><path d="M17.5 6.5l-11 11"/>',
  "check-circle": '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12.2l2.4 2.4 4.6-4.9"/>',
  alert: '<path d="M12 4.8l8.6 14.4H3.4z"/><path d="M12 10.2v3.6"/><path d="M12 16.6v.2"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11.2v4.8"/><path d="M12 8.2v.2"/>',
  "x-circle": '<circle cx="12" cy="12" r="8.5"/><path d="M9.3 9.3l5.4 5.4"/><path d="M14.7 9.3l-5.4 5.4"/>',
  upload:
    '<path d="M12 15.5V4.8"/><path d="M7.6 9.2L12 4.8l4.4 4.4"/><path d="M4.5 15.5v3.2c0 .5.4.8.9.8h13.2c.5 0 .9-.3.9-.8v-3.2"/>',
  file: '<path d="M13.5 3.5H7A1.5 1.5 0 005.5 5v14A1.5 1.5 0 007 20.5h10a1.5 1.5 0 001.5-1.5V8.5z"/><path d="M13.5 3.5v5h5"/>',
  "arrow-right": '<path d="M4.5 12h14"/><path d="M13 6.5l5.5 5.5L13 17.5"/>',
  refresh:
    '<path d="M19.5 12a7.5 7.5 0 11-2.3-5.4"/><path d="M19.5 4.5V9H15"/>',
  lock: '<rect x="5.5" y="10.5" width="13" height="9" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 017 0v2.5"/>',
  plug: '<path d="M9 3.5v5"/><path d="M15 3.5v5"/><path d="M6.5 8.5h11v3a5.5 5.5 0 01-11 0z"/><path d="M12 17v3.5"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  cpu: '<rect x="7.5" y="7.5" width="9" height="9" rx="1.5"/><rect x="10.5" y="10.5" width="3" height="3"/><path d="M10 3.8v2.4"/><path d="M14 3.8v2.4"/><path d="M10 17.8v2.4"/><path d="M14 17.8v2.4"/><path d="M3.8 10h2.4"/><path d="M3.8 14h2.4"/><path d="M17.8 10h2.4"/><path d="M17.8 14h2.4"/>',
};

export function icon(name, { size = 18, className = "" } = {}) {
  const paths = ICONS[name];
  if (!paths) {
    throw new Error(`Unknown icon: ${name}`);
  }
  return raw(
    `<svg class="icon${className ? ` ${className}` : ""}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`,
  );
}

export function hasIcon(name) {
  return Object.prototype.hasOwnProperty.call(ICONS, name);
}
