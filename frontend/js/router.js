/* Hash router. Route resolution is a pure function so it can be tested
 * without a DOM; startRouter wires hashchange events to page rendering.
 *
 * Hash routes were chosen deliberately: every page is directly navigable
 * with zero server rewrite configuration (see docs/architecture.md).
 */

import { render as toHTML } from "./ui/html.js";

export const routes = [
  { path: "/dashboard", title: "Dashboard", section: "Overview", load: () => import("./pages/dashboard.js") },
  { path: "/correction", title: "AI Correction", section: "Correction", load: () => import("./pages/correction.js") },
  { path: "/storage", title: "Storage", section: "Data", load: () => import("./pages/storage.js") },
  { path: "/tasks", title: "Task Manager", section: "Data", load: () => import("./pages/tasks.js") },
  { path: "/settings", title: "Settings", section: "System", load: () => import("./pages/settings.js") },
];

export const DEFAULT_PATH = "/dashboard";

/** Normalise a location.hash value to a route path. "/" means "redirect". */
export function parseHash(hash) {
  let value = String(hash ?? "").trim();
  if (value.startsWith("#")) value = value.slice(1);
  const path = value.split("?")[0];
  if (!path || path === "/") return "/";
  return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
}

/** Resolve a path to a route object; unknown paths get the not-found route. */
export function resolveRoute(path, table = routes) {
  const match = table.find((route) => route.path === path);
  if (match) return match;
  return {
    path,
    title: "Page not found",
    section: "Unknown",
    isNotFound: true,
    load: () => import("./pages/notfound.js"),
  };
}

/**
 * Page lifecycle contract:
 * - mount(root, { signal }) registers every DOM listener with `signal`.
 * - unmount?(root) is optional extra cleanup; the host aborts the signal and
 *   calls any cleanup returned by mount on every navigation.
 */
export function createPageHost(container) {
  let active = null;

  return {
    mount(page, options = {}) {
      active?.unmount();
      active = null;

      const controller = new AbortController();
      let cleanup;
      try {
        cleanup = page.mount?.(container, { ...options, signal: controller.signal });
      } catch (err) {
        controller.abort();
        throw err;
      }

      active = {
        unmount() {
          try {
            page.unmount?.(container, options);
          } finally {
            controller.abort();
            if (typeof cleanup === "function") cleanup();
          }
        },
      };
    },
    unmount() {
      active?.unmount();
      active = null;
    },
  };
}

export function startRouter({ container, getStartPath, onNavigate }) {
  const pageHost = createPageHost(container);
  let navigationId = 0;

  async function renderRoute() {
    const path = parseHash(window.location.hash);
    if (path === "/") {
      window.location.replace(`#${getStartPath ? getStartPath() : DEFAULT_PATH}`);
      return;
    }

    const currentNavigation = ++navigationId;
    pageHost.unmount();
    const route = resolveRoute(path);
    if (onNavigate) onNavigate(route);
    container.setAttribute("aria-busy", "true");

    try {
      const page = await route.load();
      if (currentNavigation !== navigationId) return;
      container.innerHTML = page.render ? toHTML(page.render({ path, route })) : "";
      document.title = `${route.title} · Math Checker V6`;
      window.scrollTo(0, 0);
      const heading = container.querySelector("h1");
      if (heading) {
        heading.setAttribute("tabindex", "-1");
        heading.focus({ preventScroll: true });
      }
      pageHost.mount(page, { path, route });
    } catch (err) {
      if (currentNavigation !== navigationId) return;
      console.error("Page render failed:", err);
      container.innerHTML =
        '<div class="state-panel" data-tone="error"><p class="state-panel__title">This page could not be displayed</p><p class="state-panel__desc">An unexpected interface error occurred. Try reloading the page.</p></div>';
    } finally {
      if (currentNavigation === navigationId) container.removeAttribute("aria-busy");
    }
  }

  window.addEventListener("hashchange", renderRoute);
  renderRoute();
  return {
    render: renderRoute,
    navigate(path) {
      window.location.hash = `#${path}`;
    },
  };
}
