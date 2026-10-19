import { test } from "node:test";
import assert from "node:assert/strict";

import { render } from "../js/ui/html.js";
import * as dashboard from "../js/pages/dashboard.js";
import * as correction from "../js/pages/correction.js";
import * as settings from "../js/pages/settings.js";
import * as storage from "../js/pages/storage.js";
import * as tasks from "../js/pages/tasks.js";
import * as notfound from "../js/pages/notfound.js";
import { shellTemplate } from "../js/layout/shell.js";

const pages = [
  ["dashboard", dashboard],
  ["correction", correction],
  ["settings", settings],
  ["storage", storage],
  ["tasks", tasks],
  ["not-found", notfound],
];

test("every page renders exactly one h1 heading", () => {
  for (const [name, page] of pages) {
    const markup = render(page.render({ path: "/x" }));
    const headings = markup.match(/<h1[\s>]/g) || [];
    assert.equal(headings.length, 1, `${name} should render one <h1>`);
  }
});

test("shell marks the active page and labels landmark navigation", () => {
  const markup = render(shellTemplate({ activePath: "/dashboard" }));
  assert.ok(markup.includes('aria-current="page"'));
  assert.ok(markup.includes('aria-label="Main navigation"'));
  assert.ok(markup.includes('href="#/dashboard"'));
  assert.ok(markup.includes("Math Checker V6"));
});

test("shell leaves the version label to the status response", () => {
  const markup = render(shellTemplate({ activePath: "/dashboard" }));
  assert.ok(markup.includes("data-app-version"));
  assert.ok(!markup.includes("v6.0.0"));
});

test("icon-only controls carry accessible names", () => {
  const markup = render(shellTemplate({ activePath: "/dashboard" }));
  assert.ok(markup.includes('aria-label="Collapse sidebar"'));
  assert.ok(markup.includes('aria-label="Open navigation"'));
  assert.ok(markup.includes('aria-label="Settings"'));
});

test("dashboard renders live placeholders and honest empty states", () => {
  const markup = render(dashboard.render());
  assert.ok(markup.includes('data-section="stats"'));
  assert.ok(markup.includes('data-fill="stat-students"'));
  assert.ok(markup.includes('data-fill="stat-assignments"'));
  assert.ok(markup.includes('data-fill="stat-submissions"'));
  assert.ok(markup.includes("Submissions by status"));
  assert.ok(markup.includes("Application readiness"));
  assert.ok(markup.includes("No correction jobs yet"));
  // No fabricated metrics anywhere.
  assert.ok(!markup.includes("$"));
  assert.ok(!markup.includes("%"));
});

test("dashboard readiness reflects the real database status", () => {
  const ready = dashboard.readinessRows({
    database: { status: "ready", schema_version: 1 },
    ai_provider_configured: false,
    classroom_configured: false,
  });
  const readyDatabase = ready.find((row) => row.label === "Database");
  assert.ok(readyDatabase);
  assert.match(render(readyDatabase.value), /Ready · schema 1/);

  const unavailable = dashboard.readinessRows({
    database: { status: "unavailable", schema_version: null },
    ai_provider_configured: false,
    classroom_configured: false,
  });
  assert.match(render(unavailable.find((row) => row.label === "Database").value), /Unavailable/);
});

test("dashboard submission statistics render an empty or populated state", () => {
  const empty = render(
    dashboard.statsHTML({ total: 0, missing: 0, draft: 0, submitted: 0, graded: 0, failed: 0 }),
  );
  assert.ok(empty.includes("No submissions recorded yet"));

  const populated = render(
    dashboard.statsHTML({ total: 2, missing: 0, draft: 1, submitted: 0, graded: 1, failed: 0 }),
  );
  assert.ok(populated.includes("Draft"));
  assert.ok(populated.includes("Graded"));
});

test("correction page implements tabs, file input and a disabled start action", () => {
  const markup = render(correction.render());
  assert.ok(markup.includes('role="tablist"'));
  assert.ok(markup.includes('type="file"'));
  assert.ok(markup.includes(`accept="${correction.ACCEPTED_TYPES.join(",")}"`));
  assert.ok(markup.includes("Processing arrives in a later phase"));
  assert.ok(markup.includes('data-fill="max-upload-help"'));
  assert.ok(markup.includes("Reading the current upload limit"));
  assert.ok(markup.includes("data-modal-confirm"));
  assert.ok(!markup.includes("25 MB"));
  assert.equal(correction.resolveUploadLimitMB({ max_upload_mb: 10 }), 10);
  assert.equal(correction.resolveUploadLimitMB({ max_upload_mb: 0 }), null);
  assert.equal(correction.resolveUploadLimitMB({}), null);
  const labelIndex = markup.indexOf("Start correction");
  const tagStart = markup.lastIndexOf("<button", labelIndex);
  const buttonTag = markup.slice(tagStart, markup.indexOf(">", tagStart) + 1);
  assert.ok(buttonTag.includes('disabled'), "Start correction must be disabled");
  assert.ok(buttonTag.includes('aria-disabled="true"'), "aria-disabled must be well-formed");
});

test("settings page labels its fields and exposes real server settings", () => {
  const markup = render(settings.render());
  for (const id of ["pref-start-page", "pref-density", "pref-confirm-remove", "ai-provider", "classroom-oauth"]) {
    assert.ok(markup.includes(`for="${id}"`), `label for ${id}`);
    assert.ok(markup.includes(`id="${id}"`), `control ${id}`);
  }
  assert.ok(markup.includes('data-section="server-settings"'));
  assert.ok(markup.includes("Save preferences"));
  assert.ok(markup.includes("Planned"));
  assert.ok(!markup.includes("api_key"), "no key material field names");

  const form = render(
    settings.serverSettingsForm(
      { max_upload_mb: 10, default_feedback_detail: "detailed" },
      { max_upload_mb: { minimum: 1, maximum: 25 } },
    ),
  );
  assert.ok(form.includes('id="server-max-upload"'));
  assert.ok(form.includes('id="server-feedback-detail"'));
  assert.ok(form.includes('value="10"'));
  assert.ok(form.includes('max="25"'));
  assert.ok(form.includes("currently capped at 10 MB"));
  assert.ok(form.includes("Save server settings"));

  assert.ok(markup.includes('data-fill="storage-max-upload"'));
  assert.ok(!markup.includes("25 MB per file"));
});

test("storage and task pages explain their empty state honestly", () => {
  const storageMarkup = render(storage.render());
  assert.ok(storageMarkup.includes("computed on request"));
  assert.ok(storageMarkup.includes("Storage overview"));

  const tasksMarkup = render(tasks.render());
  assert.ok(tasksMarkup.includes("Assignment correction tasks"));
  assert.ok(tasksMarkup.includes("No tasks"));
  assert.ok(tasksMarkup.includes("no task system exists yet"));
});

test("not-found page names the missing route", () => {
  const markup = render(notfound.render({ path: "/missing-page" }));
  assert.ok(markup.includes("/missing-page"));
  assert.ok(markup.includes("Page not found"));
  assert.ok(markup.includes('href="#/dashboard"'));
});
