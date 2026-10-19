import { test } from "node:test";
import assert from "node:assert/strict";

import { activeNavMatch, navItems, footerNavItems } from "../js/layout/shell.js";

test("active nav matching is exact", () => {
  assert.equal(activeNavMatch("/dashboard", "/dashboard"), true);
  assert.equal(activeNavMatch("/dashboard", "/settings"), false);
  assert.equal(activeNavMatch("/unknown", "/dashboard"), false);
});

test("every nav item has a unique path and an icon reference", () => {
  const items = [...navItems, ...footerNavItems];
  const paths = items.map((item) => item.path);
  assert.equal(new Set(paths).size, paths.length);
  for (const item of items) {
    assert.ok(item.label.length > 0);
    assert.ok(item.iconName.length > 0);
    assert.ok(item.path.startsWith("/"));
  }
});
