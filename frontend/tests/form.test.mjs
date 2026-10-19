import { test } from "node:test";
import assert from "node:assert/strict";

import {
  validateRequired,
  validateFileSize,
  validateFileType,
  textInput,
} from "../js/ui/form.js";
import { render } from "../js/ui/html.js";

test("validateRequired rejects empty and whitespace values", () => {
  assert.ok(validateRequired(""));
  assert.ok(validateRequired("   "));
  assert.ok(validateRequired(null));
  assert.equal(validateRequired("Chapter 4"), null);
});

test("validateFileSize enforces the limit at the boundary", () => {
  const max = 25 * 1024 * 1024;
  assert.equal(validateFileSize(max, max), null);
  assert.ok(validateFileSize(max + 1, max));
  assert.equal(validateFileSize(0, max), null);
});

test("validateFileType accepts the allow-list, case-insensitively", () => {
  const accepted = [".pdf", ".png", ".jpg", ".jpeg"];
  assert.equal(validateFileType("homework.pdf", accepted), null);
  assert.equal(validateFileType("PHOTO.JPEG", accepted), null);
  assert.ok(validateFileType("script.exe", accepted));
  assert.ok(validateFileType("archive.zip", accepted));
});

test("textInput renders label association, help and error wiring", () => {
  const markup = render(
    textInput({
      id: "field-1",
      label: "Assignment title",
      help: "Some help",
      error: "Broken",
      required: true,
    }),
  );
  assert.ok(markup.includes('for="field-1"'));
  assert.ok(markup.includes('id="field-1"'));
  assert.ok(markup.includes('aria-invalid="true"'));
  assert.ok(markup.includes('id="field-1-help"'));
  assert.ok(markup.includes('id="field-1-error"'));
  assert.ok(markup.includes('aria-describedby="field-1-help field-1-error"'));
});

test("form markup escapes untrusted values", () => {
  const markup = render(
    textInput({ id: "f", label: "L", value: '"><script>alert(1)</script>' }),
  );
  assert.ok(!markup.includes("<script>"));
  assert.ok(markup.includes("&lt;script&gt;"));
});
