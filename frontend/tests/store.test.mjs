import { test } from "node:test";
import assert from "node:assert/strict";

import { createStore, parsePrefs, serializePrefs, DEFAULT_PREFS, START_PAGE_OPTIONS } from "../js/store.js";

function fakeStorage() {
  const data = new Map();
  return {
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, String(value)),
  };
}

test("parsePrefs returns defaults for empty or corrupt input", () => {
  assert.deepEqual(parsePrefs(""), DEFAULT_PREFS);
  assert.deepEqual(parsePrefs(null), DEFAULT_PREFS);
  assert.deepEqual(parsePrefs("{not json"), DEFAULT_PREFS);
  assert.deepEqual(parsePrefs("[]"), DEFAULT_PREFS);
  assert.deepEqual(parsePrefs('"string"'), DEFAULT_PREFS);
});

test("parsePrefs ignores unknown keys and invalid values", () => {
  const parsed = parsePrefs(
    JSON.stringify({ startPage: "/evil", density: "huge", confirmBeforeRemove: "yes", unknownKey: 1 }),
  );
  assert.deepEqual(parsed, DEFAULT_PREFS);
});

test("parsePrefs accepts valid values", () => {
  const parsed = parsePrefs(
    JSON.stringify({ startPage: "/tasks", density: "compact", confirmBeforeRemove: false, sidebarCollapsed: true }),
  );
  assert.equal(parsed.startPage, "/tasks");
  assert.equal(parsed.density, "compact");
  assert.equal(parsed.confirmBeforeRemove, false);
  assert.equal(parsed.sidebarCollapsed, true);
});

test("all start page options are real routes", () => {
  for (const path of START_PAGE_OPTIONS) {
    assert.ok(path.startsWith("/"));
  }
  assert.ok(START_PAGE_OPTIONS.includes(DEFAULT_PREFS.startPage));
});

test("store round-trips preferences through storage", () => {
  const storage = fakeStorage();
  const store = createStore(storage);

  assert.deepEqual(store.getAll(), DEFAULT_PREFS);

  store.set("density", "compact");
  assert.equal(store.get("density"), "compact");

  // A fresh store reading the same storage sees the persisted value.
  const reopened = createStore(storage);
  assert.equal(reopened.get("density"), "compact");

  store.reset();
  assert.deepEqual(store.getAll(), DEFAULT_PREFS);
});

test("store sanitises invalid values on write", () => {
  const store = createStore(fakeStorage());
  store.set("startPage", "/not-a-page");
  assert.equal(store.get("startPage"), DEFAULT_PREFS.startPage);
});

test("store tolerates storage that throws", () => {
  const broken = {
    getItem() {
      throw new Error("nope");
    },
    setItem() {
      throw new Error("nope");
    },
  };
  const store = createStore(broken);
  assert.deepEqual(store.getAll(), DEFAULT_PREFS);
  store.set("density", "compact"); // must not throw
});

test("serializePrefs fills in defaults for partial objects", () => {
  const parsed = JSON.parse(serializePrefs({ density: "compact" }));
  assert.equal(parsed.density, "compact");
  assert.equal(parsed.startPage, DEFAULT_PREFS.startPage);
});
