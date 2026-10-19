/* Application shell: sidebar navigation, top bar and content slot.
 *
 * The shell owns navigation state (active item, collapse, mobile drawer) and
 * the server-status chip; pages render into #content through the router.
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

export const APP_VERSION_LABEL = "v6.0.0 · Phase 1";

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
  ><span class="nav-item__icon">${icon(item.iconName, { size: 18 })}</span><span class="nav-label">${item.label}</span></a>`;
}

function serverChip() {
  return html`<span class="topbar__status" data-server-chip>
    <span class="status-dot" data-state="idle" data-server-dot></span>
    <span class="topbar__status-label" data-server-label>Connecting…</span>
  </span>`;
}

export function shellTemplate({ activePath } = {}) {
  const collapsed = prefs.get("sidebarCollapsed");
  return html`
    <div class="app-shell${collapsed ? " is-collapsed" : ""}" id="app-shell">
      <div class="sidebar-overlay" data-drawer-overlay></div>
      <nav class="sidebar" id="sidebar" aria-label="Main navigation">
        <div class="sidebar__header">
          <a class="sidebar__brand" href="#/dashboard">
            <svg class="sidebar__logo" viewBox="0 0 32 32" aria-hidden="true">
              <rect width="32" height="32" rx="8" fill="var(--color-accent)"></rect>
              <path d="M9 17.5l4.5 4.5L23 11.5" stroke="var(--color-on-accent)" stroke-width="3.2" fill="none" stroke-linecap="round" stroke-linejoin="round"></path>
            </svg>
            <span class="sidebar__names">
              <span class="sidebar__name">Math Checker V6</span>
              <span class="sidebar__version">${APP_VERSION_LABEL}</span>
            </span>
          </a>
        </div>

        <div class="sidebar__section-label">Workspace</div>
        <div class="sidebar__nav">
          ${navItems.map((item) => navLink(item, activePath))}
        </div>

        <div class="sidebar__footer">
          <div class="sidebar__nav">
            ${footerNavItems.map((item) => navLink(item, activePath))}
          </div>
          <div class="sidebar__status" title="Server connection status">
            <span class="status-dot" data-state="idle" data-server-dot></span>
            <span class="sidebar__status-label" data-server-label>Connecting…</span>
          </div>
        </div>
      </nav>

      <div class="main-column">
        <header class="topbar">
          <button type="button" class="btn btn--icon drawer-toggle" data-drawer-toggle aria-label="Open navigation" aria-expanded="false" aria-controls="sidebar">
            ${icon("menu", { size: 18 })}
          </button>
          <button type="button" class="btn btn--icon collapse-toggle" data-collapse-toggle aria-label="Collapse sidebar" aria-pressed="${collapsed ? "true" : "false"}" title="Collapse sidebar">
            ${icon("panel-collapse", { size: 18 })}
          </button>
          <div class="topbar__breadcrumb">
            <span>Math Checker V6</span>
            <span class="topbar__crumb-sep" aria-hidden="true">/</span>
            <span class="topbar__page" data-page-title>—</span>
          </div>
          <div class="topbar__actions">
            ${serverChip()}
            <a class="btn btn--icon" href="#/settings" aria-label="Settings" title="Settings">
              ${icon("settings", { size: 18 })}
            </a>
          </div>
        </header>

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
  const title = shell.querySelector("[data-page-title]");
  if (title && routeTitle) title.textContent = routeTitle;
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

  const collapseToggle = shell.querySelector("[data-collapse-toggle]");
  collapseToggle?.addEventListener("click", () => {
    const collapsed = shell.classList.toggle("is-collapsed");
    collapseToggle.setAttribute("aria-pressed", collapsed ? "true" : "false");
    collapseToggle.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
    collapseToggle.setAttribute("title", collapsed ? "Expand sidebar" : "Collapse sidebar");
    prefs.set("sidebarCollapsed", collapsed);
  });

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
