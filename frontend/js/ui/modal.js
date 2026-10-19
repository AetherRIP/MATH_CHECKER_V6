/* Confirmation dialog. Markup is a pure template; behaviour (focus trap,
 * Escape, backdrop click, focus restore) lives in the DOM helpers below and is
 * only active in the browser. */

import { html } from "./html.js";
import { icon } from "../icons.js";

export function modalTemplate({
  id,
  title,
  description,
  body,
  confirmLabel = "Confirm",
  confirmTone = "primary",
  cancelLabel = "Cancel",
} = {}) {
  return html`
    <div class="modal-overlay" id="${id}" hidden>
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="${id}-title">
        <header class="modal__header">
          <h2 class="modal__title" id="${id}-title">${title}</h2>
          <button type="button" class="btn btn--ghost btn--icon" data-modal-close aria-label="Close dialog" title="Close">
            ${icon("x", { size: 16 })}
          </button>
        </header>
        ${description ? html`<p class="modal__desc">${description}</p>` : ""}
        ${body ? html`<div class="modal__body">${body}</div>` : ""}
        <footer class="modal__footer">
          <button type="button" class="btn btn--secondary" data-modal-close>${cancelLabel}</button>
          <button type="button" class="btn btn--${confirmTone}" data-modal-confirm>${confirmLabel}</button>
        </footer>
      </div>
    </div>
  `;
}

const confirmHandlers = new Map();
let lastFocused = null;

function focusables(root) {
  return Array.from(
    root.querySelectorAll(
      'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
    ),
  );
}

export function openModal(id, { onConfirm } = {}) {
  const overlay = document.getElementById(id);
  if (!overlay) return;
  if (onConfirm) confirmHandlers.set(id, onConfirm);
  lastFocused = document.activeElement;
  overlay.hidden = false;
  const targets = focusables(overlay);
  (targets[0] || overlay.querySelector(".modal") || overlay).focus?.();
}

export function closeModal(id) {
  const overlay = document.getElementById(id);
  if (!overlay || overlay.hidden) return;
  overlay.hidden = true;
  confirmHandlers.delete(id);
  if (lastFocused && typeof lastFocused.focus === "function") {
    lastFocused.focus();
  }
  lastFocused = null;
}

export function bindModalEvents() {
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    const openTrigger = target.closest("[data-modal-open]");
    if (openTrigger) {
      openModal(openTrigger.getAttribute("data-modal-open"));
      return;
    }

    const overlay = target.closest(".modal-overlay");
    if (!overlay) return;

    if (target === overlay || target.closest("[data-modal-close]")) {
      closeModal(overlay.id);
      return;
    }

    if (target.closest("[data-modal-confirm]")) {
      const handler = confirmHandlers.get(overlay.id);
      closeModal(overlay.id);
      if (handler) handler();
    }
  });

  document.addEventListener("keydown", (event) => {
    const overlay = document.querySelector(".modal-overlay:not([hidden])");
    if (!overlay) return;

    if (event.key === "Escape") {
      event.preventDefault();
      closeModal(overlay.id);
      return;
    }

    if (event.key === "Tab") {
      const targets = focusables(overlay);
      if (!targets.length) return;
      const first = targets[0];
      const last = targets[targets.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });
}
