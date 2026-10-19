/* Not-found page for unknown routes. */

import { html } from "../ui/html.js";
import { pageHeader } from "../ui/card.js";
import { button } from "../ui/button.js";
import { emptyState } from "../ui/states.js";

export function render({ path } = {}) {
  return html`
    ${pageHeader({
      title: "Page not found",
      description: "The address you opened does not match any page in this application.",
    })}
    ${emptyState({
      iconName: "alert",
      title: "Nothing lives at this route",
      description: html`No page is registered for <code>${path ?? ""}</code>. Use the navigation or go back to the dashboard.`,
      tone: "info",
      actions: button({ label: "Go to dashboard", variant: "primary", href: "#/dashboard", iconName: "arrow-right" }),
    })}
  `;
}
