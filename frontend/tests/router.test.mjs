import { test } from "node:test";
import assert from "node:assert/strict";

import { createPageHost, parseHash, resolveRoute, routes, DEFAULT_PATH } from "../js/router.js";

test("parseHash normalises hash values to route paths", () => {
  assert.equal(parseHash("#/dashboard"), "/dashboard");
  assert.equal(parseHash("/dashboard"), "/dashboard");
  assert.equal(parseHash("#/settings?tab=a"), "/settings");
  assert.equal(parseHash("#/storage/"), "/storage");
});

test("empty or root hashes mean redirect", () => {
  assert.equal(parseHash(""), "/");
  assert.equal(parseHash("#"), "/");
  assert.equal(parseHash("#/"), "/");
  assert.equal(parseHash(undefined), "/");
});

test("resolveRoute finds every registered route", () => {
  for (const route of routes) {
    const resolved = resolveRoute(route.path);
    assert.equal(resolved.path, route.path);
    assert.equal(resolved.title, route.title);
    assert.equal(resolved.isNotFound, undefined);
    assert.equal(typeof resolved.load, "function");
  }
});

test("unknown paths resolve to the not-found route", () => {
  const resolved = resolveRoute("/definitely-not-a-page");
  assert.equal(resolved.isNotFound, true);
  assert.equal(resolved.title, "Page not found");
  assert.equal(typeof resolved.load, "function");
});

test("route table is well-formed and collision-free", () => {
  const paths = routes.map((route) => route.path);
  assert.equal(new Set(paths).size, paths.length, "duplicate route paths");
  assert.ok(paths.includes(DEFAULT_PATH), "default route exists");
  for (const route of routes) {
    assert.ok(route.path.startsWith("/"), `path starts with /: ${route.path}`);
    assert.ok(route.title.length > 0);
    assert.ok(!route.path.endsWith("/"), "no trailing slashes in the table");
  }
});

test("page host tears down listeners so one click sends one request", () => {
  const container = new EventTarget();
  const host = createPageHost(container);
  let requests = 0;
  let unmounted = 0;
  const page = {
    mount(root, { signal }) {
      root.addEventListener("click", () => { requests += 1; }, { signal });
    },
    unmount() {
      unmounted += 1;
    },
  };

  host.mount(page, { path: "/dashboard" });
  host.mount(page, { path: "/dashboard" });
  assert.equal(unmounted, 1, "the previous page receives its unmount contract");

  container.dispatchEvent(new Event("click"));
  assert.equal(requests, 1, "only the current page listener remains");

  host.unmount();
  container.dispatchEvent(new Event("click"));
  assert.equal(requests, 1, "unmount removes the last listener too");
});
