/* Tiny HTML templating for Math Checker V6.
 *
 * `html` is a tagged template that escapes every interpolated value, so page
 * and component code never has to remember to escape manually. Content that
 * is already HTML (component output, icon markup) is wrapped with `raw()`.
 *
 * `html` returns a raw-marked value rather than a plain string, so components
 * compose at any depth without double-escaping. Convert the final result to a
 * string with `render()` before assigning to innerHTML.
 */

const RAW = Symbol("raw");

export function raw(value) {
  return { [RAW]: true, value: String(value ?? "") };
}

export function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderValue(value) {
  if (value === null || value === undefined || value === false || value === true) {
    return "";
  }
  if (Array.isArray(value)) {
    return value.map(renderValue).join("");
  }
  if (typeof value === "object" && RAW in value) {
    return value.value;
  }
  return esc(value);
}

function build(strings, values) {
  let out = "";
  for (let i = 0; i < strings.length; i += 1) {
    out += strings[i];
    if (i < values.length) {
      out += renderValue(values[i]);
    }
  }
  return out;
}

export function html(strings, ...values) {
  return raw(build(strings, values));
}

export function render(value) {
  return renderValue(value);
}
