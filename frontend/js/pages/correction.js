/* AI Correction workspace (layout and client-side behaviour only).
 *
 * Implemented now: selecting and validating submission files in the browser,
 * reviewing and removing them, and keeping an assignment/options draft. The
 * upload limit and default feedback detail are read from the server settings.
 * The correction engine and PDF extraction exist in the backend from Phase 3;
 * uploading, job tracking and results display are connected in Phase 4. The
 * Start button stays disabled with an explanation — never a dead control.
 */

import { html, render as toHTML } from "../ui/html.js";
import { icon } from "../icons.js";
import { pageHeader, card } from "../ui/card.js";
import { button } from "../ui/button.js";
import { badge } from "../ui/badge.js";
import { textInput, textArea, selectField, checkboxField, validateFileSize, validateFileType } from "../ui/form.js";
import { emptyState } from "../ui/states.js";
import { tabsTemplate, initTabs } from "../ui/tabs.js";
import { paginationTemplate } from "../ui/pagination.js";
import { modalTemplate, openModal } from "../ui/modal.js";
import { showToast } from "../ui/toast.js";
import { prefs } from "../store.js";
import { formatBytes } from "../format.js";
import { api } from "../api.js";

export const ACCEPTED_TYPES = [".pdf", ".png", ".jpg", ".jpeg"];
const PAGE_SIZE = 8;

/** The server's effective upload cap in MB, or null when it is not usable. */
export function resolveUploadLimitMB(settings) {
  const mb = Number(settings?.max_upload_mb);
  return Number.isFinite(mb) && mb >= 1 ? mb : null;
}

// Null until the server reports its effective upload cap. File selection is
// disabled until then so the browser never validates against a guessed limit.
let maxFileBytes = null;
let optionsTouched = false;

const draft = {
  files: [],
  nextId: 1,
  page: 1,
  fileErrors: [],
  context: { title: "", qualification: "Edexcel IGCSE Mathematics", component: "", notes: "" },
  options: {
    doubleCheck: true,
    workingFeedback: true,
    markScheme: true,
    feedbackDetail: "detailed",
  },
};

let pendingRemoveId = null;

function fileRowsHTML() {
  const start = (draft.page - 1) * PAGE_SIZE;
  const slice = draft.files.slice(start, start + PAGE_SIZE);
  return html`
    <ul class="file-list">
      ${slice.map(
        (file) => html`<li class="file-row">
          <span class="file-row__icon">${icon("file", { size: 16 })}</span>
          <span class="file-row__name" title="${file.name}">${file.name}</span>
          <span class="file-row__meta">${formatBytes(file.size)}</span>
          ${badge({ label: file.name.split(".").pop().toUpperCase(), tone: "info" })}
          <span class="file-row__actions">
            <button
              type="button"
              class="btn btn--ghost btn--icon"
              data-remove-file="${file.id}"
              aria-label="Remove ${file.name} from the selection"
              title="Remove from selection"
            >${icon("x", { size: 14 })}</button>
          </span>
        </li>`,
      )}
    </ul>
  `;
}

function reviewHTML() {
  if (!draft.files.length) {
    return emptyState({
      iconName: "file",
      title: "No submissions selected yet",
      description:
        "Choose one or more homework files above. Selected files are listed here for review before correction.",
      compact: true,
    });
  }
  const totalSize = draft.files.reduce((sum, file) => sum + file.size, 0);
  return html`
    <div class="row">
      <span class="muted text-xs">${draft.files.length} file${draft.files.length === 1 ? "" : "s"} selected · ${formatBytes(totalSize)} total</span>
    </div>
    ${fileRowsHTML()}
    ${draft.files.length > PAGE_SIZE
      ? paginationTemplate({ page: draft.page, pageSize: PAGE_SIZE, total: draft.files.length, label: "Submission pages" })
      : ""}
  `;
}

function errorsHTML() {
  if (!draft.fileErrors.length) return "";
  return html`
    <ul class="mt-4" aria-label="File selection problems">
      ${draft.fileErrors.map((message) => html`<li class="field__error">${message}</li>`)}
    </ul>
  `;
}

function submissionsPanel() {
  return html`
    ${card({
      title: "Select or upload homework submissions",
      description: "Choose the student work you want corrected.",
      body: html`
        <div class="drop-zone">
          ${icon("upload", { size: 22 })}
          <div class="field" style="width:100%;max-width:420px;margin:0;">
            <label class="field__label" for="submission-files">Submission files</label>
            <input
              class="field__control"
              type="file"
              id="submission-files"
              multiple
              accept="${ACCEPTED_TYPES.join(",")}"
              aria-describedby="submission-files-help"
              data-file-input
              disabled
            >
            <p class="field__help" id="submission-files-help" data-fill="max-upload-help">
              PDF, PNG or JPG files. Reading the current upload limit from the server…
            </p>
          </div>
        </div>
        <div class="mt-3" data-upload-limit-retry hidden>
          ${button({
            label: "Retry upload limit",
            iconName: "refresh",
            attrs: 'data-action="retry-upload-limit"',
          })}
        </div>
        <div data-file-errors>${errorsHTML()}</div>
      `,
    })}
    ${card({
      title: "Review selected files",
      description: "Check the selection before starting a correction job.",
      body: html`<div data-file-review>${reviewHTML()}</div>`,
    })}
  `;
}

function contextPanel() {
  return html`
    ${card({
      title: "Assignment context",
      description: "Describe the assignment so future correction jobs know what they are marking.",
      body: html`
        ${textInput({
          id: "ctx-title",
          label: "Assignment title",
          value: draft.context.title,
          placeholder: "e.g. Chapter 4 — Quadratic equations",
          required: true,
          help: "Stored with the job draft in this browser only.",
          attrs: 'data-draft-group="context" data-draft-key="title"',
        })}
        ${selectField({
          id: "ctx-qualification",
          label: "Qualification",
          value: draft.context.qualification,
          options: [{ value: "Edexcel IGCSE Mathematics", label: "Edexcel IGCSE Mathematics" }],
          help: "Fixed for this application.",
          attrs: 'data-draft-group="context" data-draft-key="qualification"',
        })}
        ${textInput({
          id: "ctx-component",
          label: "Paper or component",
          value: draft.context.component,
          placeholder: "e.g. Paper 2H — May 2024",
          attrs: 'data-draft-group="context" data-draft-key="component"',
        })}
        ${textArea({
          id: "ctx-notes",
          label: "Notes for the correction job",
          value: draft.context.notes,
          placeholder: "Anything the correction engine should know…",
          rows: 3,
          attrs: 'data-draft-group="context" data-draft-key="notes"',
        })}
      `,
    })}
  `;
}

function optionsPanel() {
  return html`
    ${card({
      title: "Correction options",
      description: "These options are stored with the job draft until uploads are connected in Phase 4.",
      body: html`
        ${checkboxField({
          id: "opt-double-check",
          label: "Double-check borderline marks",
          checked: draft.options.doubleCheck,
          help: "Re-verify marks that fall near a grade boundary.",
          attrs: 'data-draft-group="options" data-draft-key="doubleCheck"',
        })}
        ${checkboxField({
          id: "opt-working-feedback",
          label: "Include feedback on working",
          checked: draft.options.workingFeedback,
          help: "Comment on method, not only the final answer.",
          attrs: 'data-draft-group="options" data-draft-key="workingFeedback"',
        })}
        ${checkboxField({
          id: "opt-mark-scheme",
          label: "Verify against the mark scheme",
          checked: draft.options.markScheme,
          help: "Compare marks with the official mark scheme when one is attached.",
          attrs: 'data-draft-group="options" data-draft-key="markScheme"',
        })}
        ${selectField({
          id: "opt-feedback-detail",
          label: "Feedback detail",
          value: draft.options.feedbackDetail,
          options: [
            { value: "brief", label: "Brief — marks only" },
            { value: "detailed", label: "Detailed — marks with comments" },
          ],
          attrs: 'data-draft-group="options" data-draft-key="feedbackDetail"',
        })}
      `,
    })}
  `;
}

function jobsPanel() {
  return html`
    ${card({
      title: "Correction job status",
      description: "Running and completed jobs will be tracked here.",
      body: html`
        ${emptyState({
          iconName: "clock",
          title: "No correction jobs yet",
          description:
            "The correction engine exists in the backend, but this page does not upload files or track jobs yet. That integration arrives in Phase 4.",
          compact: true,
        })}
        <div class="mt-5">
          ${button({
            label: "Start correction",
            variant: "primary",
            iconName: "correction",
            disabled: true,
            note: "Available in Phase 4 — uploading and job tracking are not connected yet.",
          })}
        </div>
      `,
    })}
  `;
}

function resultsPanel() {
  return html`
    ${card({
      title: "Correction results",
      description: "Reviewed results and reports will appear here.",
      body: emptyState({
        iconName: "check-circle",
        title: "No results yet",
        description: "Results appear after uploads and job tracking are connected in Phase 4.",
        compact: true,
      }),
    })}
  `;
}

export function render() {
  return html`
    ${pageHeader({
      title: "AI Correction",
      description:
        "Prepare homework submissions for AI-assisted correction. File selection and configuration work today; uploading is connected in Phase 4.",
      actions: badge({ label: "Uploading arrives in Phase 4", tone: "warning", iconName: "info" }),
    })}
    ${tabsTemplate({
      id: "correction",
      label: "Correction workflow",
      activeId: "submissions",
      items: [
        { id: "submissions", label: "Submissions", iconName: "upload", content: submissionsPanel() },
        { id: "context", label: "Assignment", iconName: "file", content: contextPanel() },
        { id: "options", label: "Correction options", iconName: "settings", content: optionsPanel() },
        { id: "jobs", label: "Job status", iconName: "clock", content: jobsPanel() },
        { id: "results", label: "Results", iconName: "check-circle", content: resultsPanel() },
      ],
    })}
    ${modalTemplate({
      id: "modal-remove-file",
      title: "Remove submission?",
      description:
        "The file is only removed from this selection. Nothing is deleted from your computer.",
      confirmLabel: "Remove",
      confirmTone: "danger",
    })}
  `;
}

function refreshReview(root) {
  const review = root.querySelector("[data-file-review]");
  if (review) review.innerHTML = toHTML(reviewHTML());
  const errors = root.querySelector("[data-file-errors]");
  if (errors) errors.innerHTML = toHTML(errorsHTML());
}

function removeFile(root, id) {
  draft.files = draft.files.filter((file) => file.id !== id);
  const pages = Math.max(1, Math.ceil(draft.files.length / PAGE_SIZE));
  draft.page = Math.min(draft.page, pages);
  refreshReview(root);
}

function addFiles(root, fileList) {
  draft.fileErrors = [];
  if (maxFileBytes === null) {
    showToast("The upload limit is still loading. Try again in a moment.", { tone: "error" });
    return;
  }
  let added = 0;
  for (const file of Array.from(fileList)) {
    const typeError = validateFileType(file.name, ACCEPTED_TYPES);
    const sizeError = typeError ? null : validateFileSize(file.size, maxFileBytes);
    const error = typeError || sizeError;
    if (error) {
      draft.fileErrors.push(`${file.name}: ${error}`);
      continue;
    }
    draft.files.push({ id: draft.nextId++, name: file.name, size: file.size });
    added += 1;
  }
  if (added) {
    draft.page = Math.max(1, Math.ceil(draft.files.length / PAGE_SIZE));
    showToast(
      `${added} submission${added === 1 ? "" : "s"} added to the draft.`,
      { tone: "success" },
    );
  }
  if (draft.fileErrors.length) {
    showToast("Some files were not accepted. See the list for details.", { tone: "error" });
  }
  refreshReview(root);
}

async function loadServerSettings(root) {
  const help = root.querySelector('[data-fill="max-upload-help"]');
  const input = root.querySelector("[data-file-input]");
  const retry = root.querySelector("[data-upload-limit-retry]");
  if (retry) retry.hidden = true;
  if (help) {
    help.textContent = "PDF, PNG or JPG files. Reading the current upload limit from the server…";
  }
  try {
    const payload = await api.settings.get();
    const settings = payload.settings || {};
    const mb = resolveUploadLimitMB(settings);
    if (mb === null) {
      throw new Error("The server did not provide a valid upload limit.");
    }
    maxFileBytes = mb * 1024 * 1024;
    if (help) {
      help.textContent = `PDF, PNG or JPG files, up to ${mb} MB each. Files stay in your browser until uploading is connected in Phase 4.`;
    }
    if (input) input.disabled = false;
    if (retry) retry.hidden = true;
    if (!optionsTouched && settings.default_feedback_detail) {
      draft.options.feedbackDetail = settings.default_feedback_detail;
      const select = root.querySelector("#opt-feedback-detail");
      if (select) select.value = settings.default_feedback_detail;
    }
  } catch {
    maxFileBytes = null;
    if (input) input.disabled = true;
    if (retry) retry.hidden = false;
    if (help) {
      help.textContent =
        "The current upload limit could not be read from the server. Try again.";
    }
  }
}

export function mount(root, { signal } = {}) {
  initTabs(root, { signal });
  loadServerSettings(root);

  root.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.matches("[data-file-input]")) {
      addFiles(root, target.files || []);
      target.value = "";
      return;
    }
    const group = target.getAttribute("data-draft-group");
    const key = target.getAttribute("data-draft-key");
    if (group && key && target instanceof HTMLInputElement) {
      if (group === "options") optionsTouched = true;
      draft[group][key] = target.type === "checkbox" ? target.checked : target.value;
    }
  }, { signal });

  root.addEventListener("input", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const group = target.getAttribute("data-draft-group");
    const key = target.getAttribute("data-draft-key");
    if (group && key && target instanceof HTMLInputElement && target.type !== "checkbox") {
      if (group === "options") optionsTouched = true;
      draft[group][key] = target.value;
    }
  }, { signal });

  root.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    if (target.closest('[data-action="retry-upload-limit"]')) {
      loadServerSettings(root);
      return;
    }

    const removeBtn = target.closest("[data-remove-file]");
    if (removeBtn) {
      pendingRemoveId = Number(removeBtn.getAttribute("data-remove-file"));
      if (prefs.get("confirmBeforeRemove")) {
        openModal("modal-remove-file", {
          onConfirm: () => {
            if (pendingRemoveId !== null) removeFile(root, pendingRemoveId);
            pendingRemoveId = null;
          },
        });
      } else if (pendingRemoveId !== null) {
        removeFile(root, pendingRemoveId);
        pendingRemoveId = null;
      }
      return;
    }

    const pageBtn = target.closest("[data-page]");
    if (pageBtn && !pageBtn.hasAttribute("disabled")) {
      const page = Number(pageBtn.getAttribute("data-page"));
      if (Number.isFinite(page) && page >= 1) {
        draft.page = page;
        refreshReview(root);
      }
    }
  }, { signal });
}
