/* Math Checker V6 — application bootstrap. */

import { render } from "./ui/html.js";
import { shellTemplate, initShell, setActivePath, setAppVersion, setServerStatus } from "./layout/shell.js";
import { startRouter, DEFAULT_PATH } from "./router.js";
import { prefs } from "./store.js";
import { api } from "./api.js";

function boot() {
  const app = document.getElementById("app");
  if (!app) return;

  app.innerHTML = render(shellTemplate({ activePath: DEFAULT_PATH }));
  document.documentElement.dataset.density = prefs.get("density");

  initShell();

  startRouter({
    container: document.getElementById("content"),
    getStartPath: () => prefs.get("startPage") || DEFAULT_PATH,
    onNavigate: (route) => setActivePath(route.path, route.title),
  });

  // One status request feeds the top bar chip and the real version label;
  // pages share the same cached response.
  api.systemStatus().then(
    (status) => {
      setServerStatus("ready", "Server ready");
      setAppVersion(`v${status.version} · Phase ${status.phase}`);
    },
    () => {
      setServerStatus("offline", "Server unreachable");
      setAppVersion("Version unavailable");
    },
  );

  window.addEventListener("error", (event) => {
    console.error("Unhandled error:", event.error || event.message);
  });
  window.addEventListener("unhandledrejection", (event) => {
    console.error("Unhandled promise rejection:", event.reason);
  });
}

boot();
