/* Settings: interface preferences (browser-local) plus real server settings
 * and live diagnostics read from the backend.
 *
 * Browser preferences stay in localStorage. Operational settings live in the
 * server's SQLite database and are never stored in the browser.
 */

import { html, render as toHTML } from "../ui/html.js";
import { pageHeader, card, detailRows } from "../ui/card.js";
import { button } from "../ui/button.js";
import { badge } from "../ui/badge.js";
import { textInput, selectField, checkboxField } from "../ui/form.js";
import { loadingState, errorState } from "../ui/states.js";
import { showToast } from "../ui/toast.js";
import { prefs, DEFAULT_PREFS, START_PAGE_OPTIONS } from "../store.js";
import { api } from "../api.js";

const START_PAGE_LABELS = {
  "/dashboard": "Dashboard",
  "/correction": "AI Correction",
  "/storage": "Storage",
  "/tasks": "Task Manager",
  "/settings": "Settings",
};

export function serverSettingsForm(settings) {
  return html`
    <form class="stack" id="server-settings-form" novalidate>
      ${textInput({
        id: "server-max-upload",
        label: "Maximum upload size (MB)",
        type: "number",
        value: settings.max_upload_mb,
        required: true,
        attrs: 'min="1" max="25" step="1"',
        help: "Applies to submission files. The 25 MB maximum is part of the correction engine contract.",
      })}
      ${selectField({
        id: "server-feedback-detail",
        label: "Default feedback detail",
        value: settings.default_feedback_detail,
        options: [
          { value: "brief", label: "Brief — marks only" },
          { value: "detailed", label: "Detailed — marks with comments" },
        ],
        help: "Used as the starting option on the correction page.",
      })}
      <p class="field__error" data-server-settings-error></p>
      <div class="row">
        ${button({ label: "Save server settings", variant: "primary", type: "submit" })}
      </div>
    </form>
  `;
}

function serverSettingsCard() {
  return card({
    title: "Server settings",
    description: "Operational settings stored in the local database.",
    body: html`<div data-section="server-settings">${loadingState({ label: "Reading server settings…" })}</div>`,
  });
}

function settingsForm() {
  const current = prefs.getAll();
  return html`
    <form class="stack" id="settings-form" novalidate>
      ${card({
        title: "General",
        description: "Basic application behaviour.",
        body: html`
          ${selectField({
            id: "pref-start-page",
            label: "Start page",
            value: current.startPage,
            options: START_PAGE_OPTIONS.map((path) => ({ value: path, label: START_PAGE_LABELS[path] })),
            help: "The page shown when the application is opened without a specific address.",
          })}
          ${checkboxField({
            id: "pref-confirm-remove",
            label: "Confirm before removing submissions",
            checked: current.confirmBeforeRemove,
            help: "Ask for confirmation before removing a file from a correction draft.",
          })}
        `,
      })}

      ${card({
        title: "Appearance",
        description: "Interface preferences, stored in this browser only.",
        body: html`
          ${selectField({
            id: "pref-density",
            label: "Interface density",
            value: current.density,
            options: [
              { value: "comfortable", label: "Comfortable" },
              { value: "compact", label: "Compact" },
            ],
            help: "Compact reduces padding for high-density work.",
          })}
          <p class="field__help">
            The sidebar remembers whether it is collapsed. Animations automatically reduce when your
            system requests reduced motion.
          </p>
        `,
      })}

      ${card({
        title: "AI provider",
        description: "Correction engine configuration.",
        actions: badge({ label: "Planned · Phase 3", tone: "warning" }),
        body: html`
          ${selectField({
            id: "ai-provider",
            label: "Provider",
            value: "",
            options: [{ value: "", label: "Not available yet" }],
            disabled: true,
            note: "AI providers will be configured on the server through environment variables in a later phase. API keys are never stored in the browser or shown in this interface.",
          })}
        `,
      })}

      ${card({
        title: "Google Classroom",
        description: "Assignment and roster synchronisation.",
        actions: badge({ label: "Planned · later phase", tone: "warning" }),
        body: html`
          ${textInput({
            id: "classroom-oauth",
            label: "OAuth client",
            value: "",
            disabled: true,
            help: "Classroom integration is planned for a later phase. No credentials are collected yet.",
          })}
        `,
      })}

      ${card({
        title: "Storage and file processing",
        description: "How submissions and generated files are handled.",
        body: html`
          ${detailRows([
            { label: "Accepted submission types", value: "PDF, PNG, JPG" },
            { label: "Maximum file size", value: "25 MB per file" },
            {
              label: "Local database",
              value: "SQLite, stored inside the application data directory",
            },
            {
              label: "Temporary files",
              value: "Processing workspaces will live in the application's temporary directory",
            },
          ])}
          <div class="mt-4">
            ${button({ label: "Open storage page", href: "#/storage", iconName: "storage" })}
          </div>
        `,
      })}

      ${card({
        title: "Application information",
        description: "Version and connectivity diagnostics.",
        body: html`
          ${detailRows([
            { label: "Application", value: "Math Checker V6" },
            { label: "Interface version", value: html`<span data-fill="interface-version">—</span>` },
            { label: "Backend version", value: html`<span data-fill="backend-version">—</span>` },
            { label: "Backend connection", value: html`<span data-fill="backend-connection">—</span>` },
            { label: "Database", value: html`<span data-fill="database-status">—</span>` },
            {
              label: "Preference storage",
              value: html`<span data-fill="pref-storage">—</span>`,
            },
          ])}
        `,
        footer: html`
          ${button({ label: "Reset to defaults", variant: "secondary", attrs: 'type="button" data-action="reset"' })}
          ${button({ label: "Save preferences", variant: "primary", type: "submit" })}
        `,
      })}
    </form>
  `;
}

function applyDensity(value) {
  document.documentElement.dataset.density = value;
}

function loadServerSettings(root) {
  const section = root.querySelector('[data-section="server-settings"]');
  if (section) section.innerHTML = toHTML(loadingState({ label: "Reading server settings…" }));

  api.settings.get().then(
    (payload) => {
      if (section) section.innerHTML = toHTML(serverSettingsForm(payload.settings));
    },
    (error) => {
      if (section) {
        section.innerHTML = toHTML(
          errorState({
            title: "Server settings unavailable",
            description: error?.message || "The application server could not be reached.",
            actions: button({
              label: "Retry",
              iconName: "refresh",
              attrs: 'data-action="retry-server-settings"',
            }),
          }),
        );
      }
    },
  );
}

function loadDiagnostics(root) {
  const interfaceVersion = root.querySelector('[data-fill="interface-version"]');
  const version = root.querySelector('[data-fill="backend-version"]');
  const connection = root.querySelector('[data-fill="backend-connection"]');
  const database = root.querySelector('[data-fill="database-status"]');
  const storage = root.querySelector('[data-fill="pref-storage"]');

  if (storage) {
    let available = false;
    try {
      localStorage.setItem("mc6.probe", "1");
      localStorage.removeItem("mc6.probe");
      available = true;
    } catch {
      available = false;
    }
    storage.textContent = available ? "Available (this browser)" : "Unavailable — preferences last for this session";
  }

  api.systemStatus().then(
    (status) => {
      const label = `${status.version} (Phase ${status.phase})`;
      if (interfaceVersion) interfaceVersion.textContent = label;
      if (version) version.textContent = label;
      if (connection) connection.textContent = "Reachable";
      if (database) {
        database.textContent =
          status.database && status.database.status === "ready"
            ? `Ready · schema ${status.database.schema_version}`
            : "Unavailable";
      }
    },
    () => {
      if (interfaceVersion) interfaceVersion.textContent = "—";
      if (version) version.textContent = "—";
      if (connection) connection.textContent = "Unreachable";
      if (database) database.textContent = "Unknown";
    },
  );
}

function saveServerSettings(root, form) {
  const errorSlot = form.querySelector("[data-server-settings-error]");
  const maxUpload = Number(form.querySelector("#server-max-upload")?.value);
  const feedbackDetail = form.querySelector("#server-feedback-detail")?.value || "detailed";

  if (!Number.isInteger(maxUpload) || maxUpload < 1 || maxUpload > 25) {
    if (errorSlot) errorSlot.textContent = "Maximum upload size must be a whole number between 1 and 25 MB.";
    return;
  }
  if (errorSlot) errorSlot.textContent = "";

  api.settings.update({
    max_upload_mb: maxUpload,
    default_feedback_detail: feedbackDetail,
  }).then(
    (payload) => {
      const section = root.querySelector('[data-section="server-settings"]');
      if (section) section.innerHTML = toHTML(serverSettingsForm(payload.settings));
      showToast("Server settings saved.", { tone: "success" });
    },
    (error) => {
      if (errorSlot) errorSlot.textContent = error?.message || "The server settings could not be saved.";
    },
  );
}

export function render() {
  return html`
    ${pageHeader({
      title: "Settings",
      description:
        "Application preferences, server settings and diagnostics. Interface preferences are saved in this browser; operational settings are stored in the local database.",
    })}
    ${serverSettingsCard()}
    ${settingsForm()}
  `;
}

export function mount(root) {
  loadServerSettings(root);
  loadDiagnostics(root);

  root.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.id === "server-settings-form") {
      event.preventDefault();
      saveServerSettings(root, form);
      return;
    }
    if (form.id === "settings-form") {
      event.preventDefault();
      const startPage = root.querySelector("#pref-start-page")?.value || DEFAULT_PREFS.startPage;
      const density = root.querySelector("#pref-density")?.value || DEFAULT_PREFS.density;
      const confirmRemove = Boolean(root.querySelector("#pref-confirm-remove")?.checked);
      prefs.setAll({ startPage, density, confirmBeforeRemove: confirmRemove });
      applyDensity(density);
      showToast("Preferences saved.", { tone: "success" });
    }
  });

  root.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest('[data-action="retry-server-settings"]')) {
      loadServerSettings(root);
      return;
    }
    if (target.closest('[data-action="reset"]')) {
      prefs.reset();
      applyDensity(DEFAULT_PREFS.density);
      root.innerHTML = toHTML(render());
      loadServerSettings(root);
      loadDiagnostics(root);
      showToast("Preferences reset to defaults.", { tone: "info" });
    }
  });
}
