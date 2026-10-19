/* Toast notifications. Rendered into the #toasts live region declared in
 * index.html, so assistive technology announces them. */

import { esc } from "./html.js";

export function showToast(message, { tone = "info", timeout = 4500 } = {}) {
  if (typeof document === "undefined") return;
  const stack = document.getElementById("toasts");
  if (!stack) return;

  const toast = document.createElement("div");
  toast.className = "toast";
  toast.dataset.tone = tone;
  toast.setAttribute("role", tone === "error" ? "alert" : "status");
  toast.innerHTML = `<span>${esc(message)}</span>`;

  const close = document.createElement("button");
  close.type = "button";
  close.className = "toast__close";
  close.setAttribute("aria-label", "Dismiss notification");
  close.innerHTML =
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6.5 6.5l11 11"/><path d="M17.5 6.5l-11 11"/></svg>';

  const remove = () => {
    clearTimeout(timer);
    toast.remove();
  };
  const timer = setTimeout(remove, timeout);
  close.addEventListener("click", remove);

  toast.appendChild(close);
  stack.appendChild(toast);
}
