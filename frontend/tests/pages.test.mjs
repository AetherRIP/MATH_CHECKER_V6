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

test("icon-only controls carry accessible names", () => {
  const markup = render(shellTemplate({ activePath: "/dashboard" }));
  assert.ok(markup.includes('aria-label="Collapse sidebar"'));
  assert.ok(markup.includes('aria-label="Open navigation"'));
  assert.ok(markup.includes('aria-label="Settings"'));
});

test("dashboard shows honest zeros and live-status placeholders", () => {
  const markup = render(dashboard.render());
  assert.ok(markup.includes("No correction jobs yet"));
  assert.ok(markup.includes('data-fill="integrations"'));
  assert.ok(markup.includes("Application readiness"));
  // No fabricated metrics anywhere.
  assert.ok(!markup.includes("$"));
  assert.ok(!markup.includes("%"));
});

test("correction page implements tabs, file input and a disabled start action", () => {
  const markup = render(correction.render());
  assert.ok(markup.includes('role="tablist"'));
  assert.ok(markup.includes('type="file"'));
  assert.ok(markup.includes(`accept="${correction.ACCEPTED_TYPES.join(",")}"`));
  assert.ok(markup.includes("Processing arrives in Phase 2"));
  assert.ok(markup.includes('data-modal-confirm'));
  const labelIndex = markup.indexOf("Start correction");
  const tagStart = markup.lastIndexOf("<button", labelIndex);
  const buttonTag = markup.slice(tagStart, markup.indexOf(">", tagStart) + 1);
  assert.ok(buttonTag.includes('disabled'), "Start correction must be disabled");
  assert.ok(buttonTag.includes('aria-disabled="true"'), "aria-disabled must be well-formed");
});

test("settings page labels its fields and explains future configuration", () => {
  const markup = render(settings.render());
  for (const id of ["pref-start-page", "pref-density", "pref-confirm-remove", "ai-provider", "classroom-oauth"]) {
    assert.ok(markup.includes(`for="${id}"`), `label for ${id}`);
    assert.ok(markup.includes(`id="${id}"`), `control ${id}`);
  }
  assert.ok(markup.includes("Save preferences"));
  assert.ok(markup.includes("Planned"));
  assert.ok(!markup.includes("api_key"), "no key material field names");
});

test("storage and task pages explain their empty state honestly", () => {
  const storageMarkup = render(storage.render());
  assert.ok(storageMarkup.includes("computed on request"));
  assert.ok(storageMarkup.includes("Storage overview"));

  const tasksMarkup = render(tasks.render());
  assert.ok(tasksMarkup.includes("Assignment correction tasks"));
  assert.ok(tasksMarkup.includes("No tasks"));
  assert.ok(tasksMarkup.includes("no task system runs in Phase 1"));
});

test("not-found page names the missing route", () => {
  const markup = render(notfound.render({ path: "/missing-page" }));
  assert.ok(markup.includes("/missing-page"));
  assert.ok(markup.includes("Page not found"));
  assert.ok(markup.includes('href="#/dashboard"'));
});
