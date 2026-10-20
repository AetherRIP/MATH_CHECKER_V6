/* Single owner of document-level dismissal triggers: the Escape key and
 * backdrop clicks. Dismissible surfaces (the confirmation modal, the mobile
 * drawer) register handlers here instead of attaching their own document
 * listeners, so dismissal semantics live in exactly one place.
 *
 * Handlers decide for themselves whether they currently apply (e.g. only
 * while their surface is open). Each registration returns an unbind function.
 * No document access happens at import time, so this module is safe to
 * import from tests. */

const escapeHandlers = new Set();
const backdropHandlers = new Set();

function resolve(target) {
  return typeof target === "function" ? target() : target || null;
}

function handleKeydown(event) {
  if (event.key !== "Escape") return;
  for (const handler of [...escapeHandlers]) handler(event);
}

function handleClick(event) {
  if (!(event.target instanceof Element)) return;
  for (const { backdrop, keep, handler } of [...backdropHandlers]) {
    const backdropEl = resolve(backdrop);
    if (!backdropEl || !backdropEl.contains(event.target)) continue;
    const keepEl = resolve(keep);
    if (keepEl && keepEl.contains(event.target)) continue;
    handler(event);
  }
}

let bound = false;

function ensureBound() {
  if (bound || typeof document === "undefined") return;
  bound = true;
  document.addEventListener("keydown", handleKeydown);
  document.addEventListener("click", handleClick);
}

/** Run `handler(event)` on every Escape press. Returns an unbind function. */
export function onEscape(handler) {
  escapeHandlers.add(handler);
  ensureBound();
  return () => escapeHandlers.delete(handler);
}

/**
 * Run `handler(event)` for clicks that land on the backdrop element but
 * outside the `keep` element (the surface floating above it). `backdrop` and
 * `keep` may be elements or getter functions for dynamically rendered
 * surfaces; a falsy result means the surface is absent and nothing dismisses.
 * Returns an unbind function.
 */
export function onBackdropClick(backdrop, keep, handler) {
  const entry = { backdrop, keep, handler };
  backdropHandlers.add(entry);
  ensureBound();
  return () => backdropHandlers.delete(entry);
}
