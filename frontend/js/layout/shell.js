/* Application shell: sticky command bar with segmented navigation, status
 * cluster and content slot.
 *
 * The shell owns navigation state (active item, mobile drawer) and the
 * server-status chip; pages render into #content through the router.
 */

import { html, raw } from "../ui/html.js";
import { icon } from "../icons.js";
import { onBackdropClick, onEscape } from "../ui/dismiss.js";
import { prefs } from "../store.js";

export const navItems = [
  { path: "/dashboard", label: "Dashboard", iconName: "dashboard" },
  { path: "/correction", label: "AI Correction", iconName: "correction" },
  { path: "/storage", label: "Storage", iconName: "storage" },
  { path: "/tasks", label: "Task Manager", iconName: "tasks" },
];

export const footerNavItems = [
  { path: "/settings", label: "Settings", iconName: "settings" },
];

// The real version and phase come from /api/system/status; the shell renders
// a neutral placeholder until that response arrives.
export const APP_VERSION_PLACEHOLDER = "—";

/** Pure helper: is this nav item active for the given route path? */
export function activeNavMatch(routePath, itemPath) {
  return routePath === itemPath;
}

function navLink(item, activePath) {
  const active = activeNavMatch(activePath, item.path);
  return html`<a
    class="nav-item"
    href="#${item.path}"
    ${active ? raw('aria-current="page"') : ""}
    title="${item.label}"
  ><span class="nav-item__icon">${icon(item.iconName, { size: 16 })}</span><span class="nav-label">${item.label}</span></a>`;
}

function serverChip() {
  return html`<span class="topbar__status" data-server-chip>
    <span class="status-dot" data-state="idle" data-server-dot></span>
    <span class="topbar__status-label" data-server-label>Connecting…</span>
  </span>`;
}

export function shellTemplate({ activePath } = {}) {
  return html`
    <div class="app-shell" id="app-shell">
      <div class="sidebar-overlay" data-drawer-overlay></div>
      <header class="commandbar">
        <button type="button" class="btn btn--icon drawer-toggle" data-drawer-toggle aria-label="Open navigation" aria-expanded="false" aria-controls="commandbar-nav">
          ${icon("menu", { size: 18 })}
        </button>
        <a class="commandbar__brand" href="#/dashboard">
          <svg class="commandbar__logo" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="8" fill="var(--color-accent)"></rect>
            <path d="M9 17.5l4.5 4.5L23 11.5" stroke="var(--color-on-accent)" stroke-width="3.2" fill="none" stroke-linecap="round" stroke-linejoin="round"></path>
          </svg>
          <span class="commandbar__names">
            <span class="commandbar__name">Math Checker V6</span>
            <span class="commandbar__version" data-app-version>${APP_VERSION_PLACEHOLDER}</span>
          </span>
        </a>

        <nav class="commandbar__nav" id="commandbar-nav" aria-label="Main navigation">
          ${navItems.map((item) => navLink(item, activePath))}
          ${footerNavItems.map((item) => navLink(item, activePath))}
        </nav>

        <div class="commandbar__cluster">
          ${serverChip()}
          <a class="btn btn--icon" href="#/settings" aria-label="Settings" title="Settings">
            ${icon("settings", { size: 18 })}
          </a>
        </div>
      </header>

      <div class="main-column">
        <main class="content" id="content" tabindex="-1"></main>
      </div>
    </div>
  `;
}

export function setActivePath(path, routeTitle) {
  const shell = document.getElementById("app-shell");
  if (!shell) return;
  for (const item of [...navItems, ...footerNavItems]) {
    const link = shell.querySelector(`.nav-item[href="#${item.path}"]`);
    if (!link) continue;
    if (activeNavMatch(path, item.path)) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  }
  const title = document.querySelector("[data-page-title]");
  if (title && routeTitle) title.textContent = routeTitle;
}

export function setAppVersion(label) {
  for (const element of document.querySelectorAll("[data-app-version]")) {
    element.textContent = label;
  }
}

export function setServerStatus(state, label) {
  for (const dot of document.querySelectorAll("[data-server-dot]")) {
    dot.setAttribute("data-state", state);
  }
  for (const text of document.querySelectorAll("[data-server-label]")) {
    text.textContent = label;
  }
}

export function initShell() {
  const shell = document.getElementById("app-shell");
  if (!shell) return;

  const drawerToggle = shell.querySelector("[data-drawer-toggle]");
  const overlay = shell.querySelector("[data-drawer-overlay]");

  function closeDrawer() {
    shell.classList.remove("is-drawer-open");
    drawerToggle?.setAttribute("aria-expanded", "false");
  }

  function toggleDrawer() {
    const open = shell.classList.toggle("is-drawer-open");
    drawerToggle?.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) shell.querySelector(".nav-item")?.focus();
  }

  drawerToggle?.addEventListener("click", toggleDrawer);

  // Escape and backdrop-click dismissal come from the shared dismiss
  // registry (ui/dismiss.js), the single owner of those triggers.
  onBackdropClick(overlay, null, closeDrawer);

  shell.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof Element && target.closest(".nav-item")) {
      closeDrawer();
    }
  });

  onEscape(() => {
    if (shell.classList.contains("is-drawer-open")) {
      closeDrawer();
      drawerToggle?.focus();
    }
  });
}
