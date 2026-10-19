/* Form building blocks. Every control is explicitly labelled; help and error
 * text are wired through aria-describedby. The validation helpers are pure
 * functions so they can be unit-tested without a DOM. */

import { html, raw } from "./html.js";
import { icon } from "../icons.js";

function describedBy(id, help, error) {
  const ids = [];
  if (help) ids.push(`${id}-help`);
  if (error) ids.push(`${id}-error`);
  return ids.length ? ` aria-describedby="${ids.join(" ")}"` : "";
}

function fieldShell({ id, label, help, error, required, control, note }) {
  return html`
    <div class="field">
      <label class="field__label" for="${id}">${label}${required ? html`<span class="field__required" aria-hidden="true">*</span>` : ""}</label>
      ${control}
      ${help ? html`<p class="field__help" id="${id}-help">${help}</p>` : ""}
      ${error ? html`<p class="field__error" id="${id}-error">${error}</p>` : ""}
      ${note ? html`<p class="field__note">${icon("info", { size: 13 })}<span>${note}</span></p>` : ""}
    </div>
  `;
}

export function textInput({
  id,
  label,
  value = "",
  placeholder,
  help,
  error,
  required,
  disabled,
  type = "text",
  name,
  note,
  attrs = "",
} = {}) {
  const control = html`<input
    class="field__control"
    type="${type}"
    id="${id}"
    name="${name || id}"
    value="${value}"
    ${placeholder ? html`placeholder="${placeholder}"` : ""}
    ${required ? "required" : ""}
    ${disabled ? "disabled" : ""}
    aria-invalid="${error ? "true" : "false"}"
    ${raw(describedBy(id, help, error))}
    ${raw(attrs)}
  >`;
  return fieldShell({ id, label, help, error, required, control, note });
}

export function textArea({
  id,
  label,
  value = "",
  placeholder,
  help,
  error,
  required,
  disabled,
  name,
  note,
  rows = 3,
  attrs = "",
} = {}) {
  const control = html`<textarea
    class="field__control"
    id="${id}"
    name="${name || id}"
    rows="${rows}"
    ${placeholder ? html`placeholder="${placeholder}"` : ""}
    ${required ? "required" : ""}
    ${disabled ? "disabled" : ""}
    aria-invalid="${error ? "true" : "false"}"
    ${raw(describedBy(id, help, error))}
    ${raw(attrs)}
  >${value}</textarea>`;
  return fieldShell({ id, label, help, error, required, control, note });
}

export function selectField({
  id,
  label,
  options = [],
  value,
  help,
  error,
  required,
  disabled,
  name,
  note,
  attrs = "",
} = {}) {
  const control = html`<select
    class="field__control"
    id="${id}"
    name="${name || id}"
    ${required ? "required" : ""}
    ${disabled ? "disabled" : ""}
    aria-invalid="${error ? "true" : "false"}"
    ${raw(describedBy(id, help, error))}
    ${raw(attrs)}
  >${options.map(
    (option) => html`<option value="${option.value}" ${option.value === value ? raw("selected") : ""}>${option.label}</option>`,
  )}</select>`;
  return fieldShell({ id, label, help, error, required, control, note });
}

export function checkboxField({ id, label, checked = false, help, disabled, name, attrs = "" } = {}) {
  return html`
    <div class="checkbox-field">
      <input
        type="checkbox"
        id="${id}"
        name="${name || id}"
        ${checked ? "checked" : ""}
        ${disabled ? "disabled" : ""}
        ${help ? raw(`aria-describedby="${id}-help"`) : ""}
        ${raw(attrs)}
      >
      <span class="checkbox-field__text">
        <label class="checkbox-field__label" for="${id}">${label}</label>
        ${help ? html`<span class="field__help" id="${id}-help">${help}</span>` : ""}
      </span>
    </div>
  `;
}

/* ---- Pure validation helpers ---- */

export function validateRequired(value) {
  return String(value ?? "").trim() ? null : "This field is required.";
}

export function validateFileSize(sizeBytes, maxBytes) {
  return Number(sizeBytes) <= Number(maxBytes) ? null : "This file is larger than the maximum allowed size.";
}

export function validateFileType(fileName, acceptedExtensions) {
  const name = String(fileName ?? "").toLowerCase();
  const ok = (acceptedExtensions || []).some((ext) => name.endsWith(String(ext).toLowerCase()));
  return ok ? null : "This file type is not supported.";
}
