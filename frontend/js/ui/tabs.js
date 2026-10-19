/* Tabs with WAI-ARIA semantics and roving-tabindex keyboard support. */

import { html } from "./html.js";
import { icon } from "../icons.js";

export function tabsTemplate({ id, label, items = [], activeId } = {}) {
  const current = items.some((item) => item.id === activeId) ? activeId : items[0]?.id;
  return html`
    <div class="tabs" data-tabs>
      <div class="tabs__list" role="tablist" aria-label="${label}">
        ${items.map(
          (item) => html`<button
            type="button"
            class="tab"
            role="tab"
            id="${id}-tab-${item.id}"
            aria-controls="${id}-panel-${item.id}"
            aria-selected="${item.id === current ? "true" : "false"}"
            tabindex="${item.id === current ? "0" : "-1"}"
            data-tab="${item.id}"
          >${item.iconName ? icon(item.iconName, { size: 15 }) : ""}<span>${item.label}</span></button>`,
        )}
      </div>
      ${items.map(
        (item) => html`<div
          class="tab-panel"
          role="tabpanel"
          id="${id}-panel-${item.id}"
          aria-labelledby="${id}-tab-${item.id}"
          tabindex="0"
          data-panel="${item.id}"
          ${item.id === current ? "" : "hidden"}
        >${item.content}</div>`,
      )}
    </div>
  `;
}

function selectTab(root, tabId) {
  const tabs = Array.from(root.querySelectorAll("[data-tab]"));
  const panels = Array.from(root.querySelectorAll("[data-panel]"));
  for (const tab of tabs) {
    const active = tab.dataset.tab === tabId;
    tab.setAttribute("aria-selected", active ? "true" : "false");
    tab.tabIndex = active ? 0 : -1;
  }
  for (const panel of panels) {
    panel.hidden = panel.dataset.panel !== tabId;
  }
}

export function initTabs(root, { signal } = {}) {
  for (const tabsRoot of root.querySelectorAll("[data-tabs]")) {
    tabsRoot.addEventListener("click", (event) => {
      const tab = event.target instanceof Element ? event.target.closest("[data-tab]") : null;
      if (tab) selectTab(tabsRoot, tab.dataset.tab);
    }, { signal });

    tabsRoot.addEventListener("keydown", (event) => {
      const tab = event.target instanceof Element ? event.target.closest("[data-tab]") : null;
      if (!tab) return;
      const tabs = Array.from(tabsRoot.querySelectorAll("[data-tab]"));
      const index = tabs.indexOf(tab);
      let next = null;
      if (event.key === "ArrowRight") next = tabs[(index + 1) % tabs.length];
      else if (event.key === "ArrowLeft") next = tabs[(index - 1 + tabs.length) % tabs.length];
      else if (event.key === "Home") next = tabs[0];
      else if (event.key === "End") next = tabs[tabs.length - 1];
      if (next) {
        event.preventDefault();
        selectTab(tabsRoot, next.dataset.tab);
        next.focus();
      }
    }, { signal });
  }
}
