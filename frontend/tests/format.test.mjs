import { test } from "node:test";
import assert from "node:assert/strict";

import { formatBytes, formatCount } from "../js/format.js";

test("formatBytes renders sensible human units", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(1024), "1.0 KB");
  assert.equal(formatBytes(25 * 1024 * 1024), "25 MB");
  assert.equal(formatBytes(1536), "1.5 KB");
  assert.equal(formatBytes(3 * 1024 ** 4), "3.0 TB");
});

test("formatBytes rejects nonsense input", () => {
  assert.equal(formatBytes(-1), "—");
  assert.equal(formatBytes("abc"), "—");
  assert.equal(formatBytes(NaN), "—");
});

test("formatCount renders integers", () => {
  assert.equal(formatCount(0), "0");
  assert.equal(formatCount(1234), "1,234");
});
