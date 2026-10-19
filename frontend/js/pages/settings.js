/* Settings: interface preferences (honestly persisted) plus clearly marked
 * placeholders for configuration that arrives in later phases.
 *
 * Nothing here collects or displays API keys or credentials — future AI and
 * Classroom configuration is server-side only, and this page says so instead
 * of pretending to manage secrets.
 */

import { html, render as toHTML } from "../ui/html.js";
import { pageHeader, card, detailRows } from "../ui/card.js";
import { button, linkButton } from "../ui/button.js";
import { badge } from "../ui/badge.js";
import { textInput, selectField, checkboxField } from "../ui/form.js";
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
        actions: badge({ label: "Planned · Phase 2", tone: "warning" }),
        body: html`
          ${selectField({
            id: "ai-provider",
            label: "Provider",
            value: "",
            options: [{ value: "", label: "Not available in Phase 1" }],
            disabled: true,
            note: "AI providers will be configured on the server through environment variables in Phase 2. API keys are never stored in the browser or shown in this interface.",
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
            help: "Classroom integration is planned for a later phase. No credentials are collected in Phase 1.",
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
              label: "Temporary files",
              value: "Processing workspaces will live in the application's temporary directory",
            },
          ])}
          <div class="mt-4">
            ${linkButton({ label: "Open storage page", href: "#/storage", iconName: "storage" })}
          </div>
        `,
      })}

      ${card({
        title: "Application information",
        description: "Version and connectivity diagnostics.",
        body: html`
          ${detailRows([
            { label: "Application", value: "Math Checker V6" },
            { label: "Interface version", value: "6.0.0 (Phase 1)" },
            { label: "Backend version", value: html`<span data-fill="backend-version">—</span>` },
            { label: "Backend connection", value: html`<span data-fill="backend-connection">—</span>` },
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

function loadDiagnostics(root) {
  const version = root.querySelector('[data-fill="backend-version"]');
  const connection = root.querySelector('[data-fill="backend-connection"]');
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
      if (version) version.textContent = `${status.version} (Phase ${status.phase})`;
      if (connection) connection.textContent = "Reachable";
    },
    () => {
      if (version) version.textContent = "—";
      if (connection) connection.textContent = "Unreachable";
    },
  );
}

export function render() {
  return html`
    ${pageHeader({
      title: "Settings",
      description:
        "Application preferences and configuration placeholders. Interface preferences are saved in this browser; server configuration arrives in later phases.",
    })}
    ${settingsForm()}
  `;
}

export function mount(root) {
  loadDiagnostics(root);

  const form = root.querySelector("#settings-form");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const startPage = root.querySelector("#pref-start-page")?.value || DEFAULT_PREFS.startPage;
    const density = root.querySelector("#pref-density")?.value || DEFAULT_PREFS.density;
    const confirmRemove = Boolean(root.querySelector("#pref-confirm-remove")?.checked);
    prefs.setAll({ startPage, density, confirmBeforeRemove: confirmRemove });
    applyDensity(density);
    showToast("Preferences saved.", { tone: "success" });
  });

  root.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof Element && target.closest('[data-action="reset"]')) {
      prefs.reset();
      applyDensity(DEFAULT_PREFS.density);
      root.innerHTML = toHTML(render());
      mount(root);
      showToast("Preferences reset to defaults.", { tone: "info" });
    }
  });
}
