/* AI Correction workspace.
 *
 * The browser owns selection and presentation only. It validates obvious
 * file/title mistakes, uploads multipart data to the backend, polls the
 * durable job state, and renders the report returned from storage. All PDF
 * processing, provider calls and marking rules stay in the backend engine.
 */

import { html, render as toHTML } from "../ui/html.js";
import { icon } from "../icons.js";
import { pageHeader, card, detailRows } from "../ui/card.js";
import { button } from "../ui/button.js";
import { badge } from "../ui/badge.js";
import { dataTable } from "../ui/table.js";
import {
  textInput,
  textArea,
  selectField,
  validateFileSize,
  validateFileType,
} from "../ui/form.js";
import { emptyState, errorState, loadingState } from "../ui/states.js";
import { tabsTemplate, initTabs, selectTab } from "../ui/tabs.js";
import { paginationTemplate } from "../ui/pagination.js";
import { modalTemplate, openModal } from "../ui/modal.js";
import { showToast } from "../ui/toast.js";
import { prefs } from "../store.js";
import { formatBytes } from "../format.js";
import { api } from "../api.js";

export const ACCEPTED_TYPES = [".pdf", ".png", ".jpg", ".jpeg"];
const PAGE_SIZE = 8;
const POLL_INTERVAL_MS = 2000;
const JOB_STATUS_LABELS = {
  queued: "Queued",
  processing: "Processing",
  completed: "Completed",
  failed: "Failed",
};
const STATUS_TONES = {
  queued: "info",
  processing: "info",
  completed: "success",
  failed: "error",
};
const REPORT_STATUS_LABELS = {
  completed: "Complete",
  partial: "Partial — review needed",
};

/** The server's effective upload cap in MB, or null when it is not usable. */
export function resolveUploadLimitMB(settings) {
  const mb = Number(settings?.max_upload_mb);
  return Number.isFinite(mb) && mb >= 1 ? mb : null;
}

function initialState() {
  return {
    studentFiles: [],
    schemeFiles: [],
    nextId: 1,
    page: 1,
    fileErrors: [],
    context: {
      title: "",
      qualification: "Edexcel IGCSE Mathematics",
      component: "",
      notes: "",
      markScheme: "",
    },
    options: { feedbackDetail: "detailed", maxScore: "" },
    maxFileBytes: null,
    settingsLoaded: false,
    engine: null,
    engineAvailable: false,
    jobsAvailable: false,
    jobs: [],
    jobsError: null,
    activeJobId: null,
    job: null,
    report: null,
    reportError: null,
    submitError: null,
    pollError: null,
    submitting: false,
    pendingKey: null,
    pollTimer: null,
    mounted: 0,
  };
}

let state = initialState();
let pendingRemove = null;

function jobFromHash() {
  const hash = String(window.location.hash || "");
  const match = hash.match(/[?&]job=([^&]+)/);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return null;
  }
}

function setJobHash(jobId) {
  try {
    const next = jobId
      ? `#/correction?job=${encodeURIComponent(jobId)}`
      : "#/correction";
    window.history.replaceState(null, "", next);
  } catch {
    /* history is unavailable in some embedded browsers; the page still works */
  }
}

export function jobStatusLabel(status) {
  return JOB_STATUS_LABELS[status] || status || "Unknown";
}

function statusBadge(status) {
  return badge({
    label: jobStatusLabel(status),
    tone: STATUS_TONES[status] || "neutral",
  });
}

export function formatMark(awarded, outOf) {
  if (awarded === null || awarded === undefined) return "Not marked";
  if (outOf === null || outOf === undefined) return `${awarded} / ?`;
  return `${awarded} / ${outOf}`;
}

function shortId(jobId) {
  const text = String(jobId || "");
  return text.length > 12 ? `${text.slice(0, 8)}…${text.slice(-4)}` : text;
}

function formatTimestamp(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function fileRowsHTML(files, role) {
  if (!files.length) return "";
  return html`
    <ul class="file-list">
      ${files.map(
        (file) => html`<li class="file-row">
          <span class="file-row__icon">${icon("file", { size: 16 })}</span>
          <span class="file-row__name" title="${file.name}">${file.name}</span>
          <span class="file-row__meta">${formatBytes(file.size)}</span>
          ${badge({
            label: file.name.split(".").pop()?.toUpperCase() || "FILE",
            tone: "info",
          })}
          <span class="file-row__actions">
            <button
              type="button"
              class="btn btn--ghost btn--icon"
              data-remove-file="${file.id}"
              data-file-role="${role}"
              aria-label="Remove ${file.name} from the selection"
              title="Remove from selection"
            >${icon("x", { size: 14 })}</button>
          </span>
        </li>`,
      )}
    </ul>
  `;
}

function paginatedFilesHTML(files, role) {
  const pages = Math.max(1, Math.ceil(files.length / PAGE_SIZE));
  const page = Math.min(state.page, pages);
  const slice = files.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  return html`
    ${fileRowsHTML(slice, role)}
    ${files.length > PAGE_SIZE
      ? paginationTemplate({
          page,
          pageSize: PAGE_SIZE,
          total: files.length,
          label: "Submission pages",
        })
      : ""}
  `;
}

function reviewHTML() {
  const { studentFiles, schemeFiles } = state;
  if (!studentFiles.length && !schemeFiles.length) {
    return emptyState({
      iconName: "file",
      title: "No files selected yet",
      description:
        "Choose student work and the corresponding mark scheme above. The server validates the actual file bytes before a job starts.",
      compact: true,
    });
  }
  return html`
    <div class="stack--tight">
      ${studentFiles.length
        ? html`<div>
            <p class="field__label">Student work</p>
            ${paginatedFilesHTML(studentFiles, "submission")}
          </div>`
        : ""}
      ${schemeFiles.length
        ? html`<div>
            <p class="field__label">Mark scheme files</p>
            ${fileRowsHTML(schemeFiles, "mark_scheme")}
          </div>`
        : ""}
    </div>
  `;
}

function errorsHTML() {
  if (!state.fileErrors.length) return "";
  return html`
    <ul class="mt-4" aria-label="File selection problems">
      ${state.fileErrors.map((message) => html`<li class="field__error">${message}</li>`)}
    </ul>
  `;
}

function submissionsPanel() {
  return html`
    ${card({
      title: "Student work",
      description: "Choose the pages or files that make up one student's submission.",
      body: html`
        <div class="drop-zone">
          ${icon("upload", { size: 24 })}
          <strong>Attach student work</strong>
          <div class="field" style="width:100%;max-width:460px;margin:0;">
            <label class="field__label" for="submission-files">Submission files</label>
            <input
              class="field__control"
              type="file"
              id="submission-files"
              multiple
              accept="${ACCEPTED_TYPES.join(",")}"
              aria-describedby="submission-files-help"
              data-file-input="submission"
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
      title: "Mark scheme",
      description:
        "The engine will not mark without the scheme. Attach a file, paste the text, or provide both.",
      body: html`
        <div class="field">
          <label class="field__label" for="scheme-files">Mark-scheme files</label>
          <input
            class="field__control"
            type="file"
            id="scheme-files"
            multiple
            accept="${ACCEPTED_TYPES.join(",")}"
            aria-describedby="scheme-files-help"
            data-file-input="mark_scheme"
            disabled
          >
          <p class="field__help" id="scheme-files-help">
            PDF, PNG or JPG. The scheme is sent to the engine, never displayed in the browser.
          </p>
        </div>
        ${textArea({
          id: "ctx-mark-scheme",
          label: "Or paste mark-scheme text",
          value: state.context.markScheme,
          placeholder: "Copy the question numbers, marking criteria and maximum marks here…",
          rows: 5,
          help: "Useful for a small scheme or when the scanned scheme cannot be uploaded.",
          attrs: 'data-draft-group="context" data-draft-key="markScheme"',
        })}
      `,
    })}
    ${card({
      title: "Review selected files",
      description: "Check filenames, types and sizes before uploading.",
      body: html`<div data-file-review>${reviewHTML()}</div>`,
    })}
  `;
}

function contextPanel() {
  return html`
    ${card({
      title: "Assignment context",
      description: "Describe the work so the job and its saved result are identifiable later.",
      body: html`
        ${textInput({
          id: "ctx-title",
          label: "Assignment title",
          value: state.context.title,
          placeholder: "e.g. Chapter 4 — Quadratic equations",
          required: true,
          help: "Stored with the durable correction job.",
          attrs: 'data-draft-group="context" data-draft-key="title"',
        })}
        ${selectField({
          id: "ctx-qualification",
          label: "Qualification",
          value: state.context.qualification,
          options: [{ value: "Edexcel IGCSE Mathematics", label: "Edexcel IGCSE Mathematics" }],
          help: "Fixed for this application.",
          attrs: 'data-draft-group="context" data-draft-key="qualification"',
        })}
        ${textInput({
          id: "ctx-component",
          label: "Paper or component",
          value: state.context.component,
          placeholder: "e.g. Paper 2H — May 2024",
          attrs: 'data-draft-group="context" data-draft-key="component"',
        })}
        ${textArea({
          id: "ctx-notes",
          label: "Instructions or notes for the correction",
          value: state.context.notes,
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
      description: "Only options supported by the Phase 3 engine are shown.",
      body: html`
        ${selectField({
          id: "opt-feedback-detail",
          label: "Feedback detail",
          value: state.options.feedbackDetail,
          options: [
            { value: "brief", label: "Brief — marks only" },
            { value: "detailed", label: "Detailed — marks with comments" },
          ],
          attrs: 'data-draft-group="options" data-draft-key="feedbackDetail"',
        })}
        ${textInput({
          id: "opt-max-score",
          label: "Expected total marks (optional)",
          type: "number",
          value: state.options.maxScore,
          placeholder: "e.g. 80",
          attrs: 'min="0" step="0.5" data-draft-group="options" data-draft-key="maxScore"',
          help: "When supplied, a different marked total is flagged for review. It is not used to invent marks.",
        })}
        <p class="field__note">
          ${icon("info", { size: 13 })}
          <span>Mark-scheme verification is mandatory and built into the engine. There is no separate toggle.</span>
        </p>
      `,
    })}
  `;
}

function draftIssues() {
  const issues = [];
  if (!state.settingsLoaded) issues.push("Waiting for the server upload limit.");
  if (!state.jobsAvailable) issues.push("Correction jobs are unavailable.");
  if (!state.engineAvailable) {
    issues.push(
      state.engine?.reason || "The correction engine is not configured.",
    );
  }
  if (!String(state.context.title || "").trim()) issues.push("Add an assignment title.");
  if (!state.studentFiles.length) issues.push("Select at least one student file.");
  if (!state.schemeFiles.length && !String(state.context.markScheme || "").trim()) {
    issues.push("Attach the mark scheme or paste its text.");
  }
  const total = state.studentFiles.length + state.schemeFiles.length;
  if (total > 12) issues.push("Attach at most 12 files in total.");
  const maxScore = String(state.options.maxScore ?? "").trim();
  if (maxScore) {
    const number = Number(maxScore);
    if (!Number.isFinite(number) || number <= 0) {
      issues.push("Expected total marks must be a positive number.");
    }
  }
  return issues;
}

export function validateDraft(draft, { engineAvailable = true, jobsAvailable = true } = {}) {
  const issues = [];
  if (!jobsAvailable) issues.push("Correction jobs are unavailable.");
  if (!engineAvailable) issues.push("The correction engine is not configured.");
  if (!String(draft?.context?.title || "").trim()) issues.push("Add an assignment title.");
  if (!draft?.studentFiles?.length) issues.push("Select at least one student file.");
  if (!draft?.schemeFiles?.length && !String(draft?.context?.markScheme || "").trim()) {
    issues.push("Attach the mark scheme or paste its text.");
  }
  const total = (draft?.studentFiles?.length || 0) + (draft?.schemeFiles?.length || 0);
  if (total > 12) issues.push("Attach at most 12 files in total.");
  const maxScore = String(draft?.options?.maxScore ?? "").trim();
  if (maxScore) {
    const number = Number(maxScore);
    if (!Number.isFinite(number) || number <= 0) {
      issues.push("Expected total marks must be a positive number.");
    }
  }
  return issues;
}

function canStart() {
  return !state.submitting && draftIssues().length === 0;
}

function jobsHTML(jobs) {
  if (!jobs.length) {
    return emptyState({
      iconName: "clock",
      title: "No correction jobs yet",
      description: "Start a correction to create a durable job. Jobs remain available after a refresh or restart.",
      compact: true,
    });
  }
  return dataTable({
    caption: "Recent jobs are read from the local database; selecting one loads its saved state.",
    columns: [
      { key: "job", label: "Job" },
      { key: "assignment", label: "Assignment" },
      { key: "status", label: "Status" },
      { key: "created", label: "Created" },
      { key: "action", label: "Action" },
    ],
    rows: jobs.map((job) => ({
      key: job.job_id,
      cells: {
        job: html`<code title="${job.job_id}">${shortId(job.job_id)}</code>`,
        assignment: job.assignment_title,
        status: statusBadge(job.status),
        created: formatTimestamp(job.created_at),
        action: html`<button type="button" class="btn btn--ghost" data-open-job="${job.job_id}">
          ${job.job_id === state.activeJobId ? "Viewing" : "Open"}
        </button>`,
      },
    })),
  });
}

function activeJobHTML() {
  const job = state.job;
  if (!job) return "";
  const reportReady = job.status === "completed" && job.report_status;
  const stages = [
    { id: "validate", label: "Validated", state: "done" },
    { id: "queue", label: "Queued", state: job.status === "queued" ? "active" : "done" },
    { id: "run", label: "Marking", state: job.status === "processing" ? "active" : job.status === "completed" ? "done" : "" },
    { id: "report", label: "Results", state: reportReady ? "done" : job.status === "failed" ? "error" : "" },
  ];
  return html`
    <div class="well mt-4" data-active-job="${job.job_id}">
      <div class="row">
        ${statusBadge(job.status)}
        <strong>Job ${shortId(job.job_id)}</strong>
        <span class="muted text-xs">${job.assignment_title}</span>
      </div>
      <p class="field__help mt-2">
        Full identifier: <code>${job.job_id}</code>
      </p>
      <div class="mt-3 stage-track" aria-label="Job progress">
        ${stages.map((stage, index) => html`${stage.state || reportReady || index === 0 ? html`<span class="stage-track__step" data-state="${stage.state || "pending"}"><span class="stage-track__step-icon">${stage.state === "done" ? icon("check-circle", { size: 12 }) : stage.state === "error" ? icon("alert", { size: 12 }) : ""}</span>${stage.label}</span>` : html`<span class="stage-track__step"><span class="stage-track__step-icon"></span>${stage.label}</span>`}${index < stages.length - 1 ? html`<span class="stage-track__link"></span>` : ""}`)}
      </div>
      ${detailRows([
        { label: "Created", value: formatTimestamp(job.created_at) },
        { label: "Started", value: formatTimestamp(job.started_at) },
        { label: "Finished", value: formatTimestamp(job.completed_at) },
        {
          label: "Report",
          value: job.report_status
            ? REPORT_STATUS_LABELS[job.report_status] || job.report_status
            : "Not available",
        },
        {
          label: "Marks",
          value:
            job.awarded === null || job.awarded === undefined
              ? "Not determinable"
              : formatMark(job.awarded, job.out_of),
        },
      ])}
      ${job.files?.length
        ? html`<div class="mt-3">
            <p class="field__label">Input files</p>
            <ul class="file-list">
              ${job.files.map(
                (file) => html`<li class="file-row">
                  <span class="file-row__icon">${icon("file", { size: 16 })}</span>
                  <span class="file-row__name">${file.filename}</span>
                  <span class="file-row__meta">${file.role === "mark_scheme" ? "Mark scheme" : "Submission"} · ${formatBytes(file.size_bytes)}</span>
                </li>`,
              )}
            </ul>
          </div>`
        : ""}
      ${job.error
        ? html`<div class="mt-3">${errorState({ title: "Correction failed", description: job.error })}</div>`
        : ""}
      ${reportReady
        ? html`<div class="mt-3">
            ${button({
              label: "Open results",
              iconName: "check-circle",
              attrs: 'data-action="view-results"',
            })}
          </div>`
        : ""}
    </div>
  `;
}

function jobsContentHTML() {
  const issues = draftIssues();
  const note = state.submitting
    ? "Uploading and creating the durable job…"
    : issues.length
      ? issues.join(" ")
      : "The server validates every file and then queues the job.";
  return html`
    ${state.submitError
      ? errorState({
          title: "Correction could not start",
          description: state.submitError,
          actions: button({
            label: "Try again",
            iconName: "refresh",
            attrs: 'data-action="start-correction"',
          }),
        })
      : ""}
    ${state.pollError
      ? errorState({
          title: "Status can no longer be refreshed",
          description: `${state.pollError} The job is saved on the server; retry to load its current state.`,
          actions: button({
            label: "Retry status",
            iconName: "refresh",
            attrs: 'data-action="refresh-job"',
          }),
        })
      : ""}
    <div class="row">
      ${button({
        label: state.submitting ? "Starting…" : "Start correction",
        variant: "primary",
        iconName: "correction",
        disabled: !canStart(),
        attrs: 'data-action="start-correction"',
        note,
      })}
      ${state.jobsError
        ? button({
            label: "Retry job list",
            iconName: "refresh",
            attrs: 'data-action="retry-jobs"',
          })
        : ""}
    </div>
    ${state.submitting ? html`<div class="mt-4">${loadingState({ label: "Uploading files and creating the job…" })}</div>` : ""}
    ${activeJobHTML()}
    <div class="mt-5">
      ${state.jobsError
        ? errorState({
            title: "Recent jobs unavailable",
            description: state.jobsError,
            actions: button({
              label: "Retry",
              iconName: "refresh",
              attrs: 'data-action="retry-jobs"',
            }),
          })
        : jobsHTML(state.jobs)}
    </div>
  `;
}

function jobsPanel() {
  return card({
    title: "Correction job",
    description: "Jobs are processed in the backend and remain available after a restart.",
    body: html`<div data-section="jobs">${jobsContentHTML()}</div>`,
  });
}

function feedbackCell(item) {
  const details = [];
  if (item.student_answer || item.scheme_answer) {
    details.push(
      html`<p class="text-xs muted">Student answer: ${item.student_answer || "—"} · Scheme: ${item.scheme_answer || "—"}</p>`,
    );
  }
  if (item.student_evidence) {
    details.push(html`<p class="text-xs"><strong>Evidence:</strong> ${item.student_evidence}</p>`);
  }
  if (item.scheme_evidence) {
    details.push(html`<p class="text-xs"><strong>Scheme:</strong> ${item.scheme_evidence}</p>`);
  }
  if (item.criteria?.length) {
    details.push(
      html`<ul class="text-xs">${item.criteria.map((criterion) => html`<li>${criterion}</li>`)}</ul>`,
    );
  }
  if (item.verification) {
    details.push(html`<p class="text-xs"><strong>Check:</strong> ${item.verification}</p>`);
  }
  if (item.warnings?.length) {
    details.push(
      html`<ul class="text-xs field__error">${item.warnings.map((warning) => html`<li>${warning}</li>`)}</ul>`,
    );
  }
  if (item.review_flags?.length) {
    details.push(
      html`<div class="row">${item.review_flags.map((flag) => badge({ label: flag, tone: "warning" }))}</div>`,
    );
  }
  return html`
    <p>${item.feedback || "No feedback supplied."}</p>
    ${details.length
      ? html`<details class="mt-2">
          <summary class="text-xs">Evidence and checks</summary>
          ${details}
        </details>`
      : ""}
  `;
}

export function reportHTML(report) {
  const complete = report.status === "completed";
  const items = report.items || [];
  return html`
    ${!complete
      ? html`<div class="mb-4">
          ${errorState({
            title: "Partial correction — not a final score",
            description:
              "One or more questions could not be resolved or verified. The percentage is intentionally withheld; review the question-level warnings.",
          })}
        </div>`
      : ""}
    ${report.summary ? html`<p class="mb-4">${report.summary}</p>` : ""}
    <div class="stat-grid">
      <div class="stat-card">
        <span class="stat-card__label">Marks</span>
        <span class="stat-card__value">${formatMark(report.awarded, report.out_of)}</span>
      </div>
      <div class="stat-card">
        <span class="stat-card__label">Percentage</span>
        <span class="stat-card__value">${
          Number.isFinite(report.percentage) ? `${report.percentage}%` : "Withheld"
        }</span>
        ${Number.isFinite(report.percentage) ? "" : html`<span class="stat-card__hint">Not shown for a partial result</span>`}
        <span class="stat-card__accent"></span>
      </div>
      <div class="stat-card" data-tone="${report.review_required ? "warning" : "success"}">
        <span class="stat-card__label">Review required</span>
        <span class="stat-card__value">${report.review_required ? "Yes" : "No"}</span>
        <span class="stat-card__accent"></span>
      </div>
    </div>
    ${detailRows([
      {
        label: "Report status",
        value: complete
          ? badge({ label: "Complete", tone: "success" })
          : badge({ label: "Partial — review needed", tone: "warning" }),
      },
      { label: "Engine", value: report.engine || "—" },
      { label: "Created", value: formatTimestamp(report.created_at) },
    ])}
    ${report.unresolved?.length
      ? html`<div class="mt-4">
          ${errorState({
            title: "Unresolved questions",
            description: `These questions were not resolved: ${report.unresolved.join(", ")}. They are not confirmed zeros.`,
          })}
        </div>`
      : ""}
    ${report.warnings?.length
      ? html`<div class="mt-4">
          <p class="field__label">Warnings</p>
          <ul>${report.warnings.map((warning) => html`<li class="field__error">${warning}</li>`)}</ul>
        </div>`
      : ""}
    <div class="mt-4">
      ${dataTable({
        columns: [
          { key: "question", label: "Question" },
          { key: "mark", label: "Mark", numeric: true },
          { key: "status", label: "Status" },
          { key: "feedback", label: "Feedback and evidence" },
        ],
        rows: items.map((item) => ({
          key: item.label,
          cells: {
            question: item.label,
            mark: formatMark(item.awarded, item.out_of),
            status: item.status === "marked"
              ? badge({ label: "Marked", tone: "success" })
              : badge({ label: item.status, tone: "warning" }),
            feedback: feedbackCell(item),
          },
        })),
        empty: {
          iconName: "alert",
          title: "No question results",
          description: "The job is complete but contains no question rows.",
        },
      })}
    </div>
  `;
}

function resultsContentHTML() {
  if (!state.activeJobId) {
    return emptyState({
      iconName: "check-circle",
      title: "No result selected",
      description: "Start a correction or open a recent job to see its persisted results.",
      compact: true,
    });
  }
  const job = state.job;
  if (!job) {
    return state.pollError
      ? errorState({
          title: "Job unavailable",
          description: state.pollError,
          actions: button({
            label: "Retry",
            iconName: "refresh",
            attrs: 'data-action="refresh-job"',
          }),
        })
      : loadingState({ label: "Reading the saved correction job…" });
  }
  if (job.status === "failed") {
    return errorState({
      title: "This correction failed",
      description: job.error || "The job failed without a result. No marks were recorded.",
    });
  }
  if (job.status === "queued" || job.status === "processing") {
    return loadingState({
      label:
        job.status === "queued"
          ? "Queued — waiting for a processing slot."
          : "Processing — the engine is marking the uploaded work.",
    });
  }
  if (state.reportError) {
    return errorState({
      title: "Stored result unavailable",
      description: state.reportError,
      actions: button({
        label: "Retry result",
        iconName: "refresh",
        attrs: 'data-action="refresh-job"',
      }),
    });
  }
  if (!state.report) {
    return loadingState({ label: "Reading the saved result…" });
  }
  return reportHTML(state.report);
}

function resultsPanel() {
  return card({
    title: "Correction results",
    description: "Question-level marks and evidence read from the durable report. The browser never recalculates marks.",
    body: html`<div data-section="results">${resultsContentHTML()}</div>`,
  });
}

function engineBadge() {
  if (!state.engine) {
    return badge({ label: "Checking engine…", tone: "neutral", iconName: "clock" });
  }
  if (state.engineAvailable) {
    return badge({ label: "Engine ready", tone: "success", iconName: "check-circle" });
  }
  return badge({ label: "Engine unavailable", tone: "warning", iconName: "info" });
}

export function render() {
  return html`
    ${pageHeader({
      eyebrow: "Correction workspace",
      title: "AI Correction",
      description:
        "Upload student work and its mark scheme, run the real correction engine, and inspect the persisted per-question result.",
      actions: engineBadge(),
    })}
    <div class="page-rail">
      <div>
        <div class="rail-block">
          <div>
            <p class="section-label mb-2">Workflow</p>
            ${card({
              title: "How a correction runs",
              body: html`<ol class="stack--tight text-xs muted">
                <li>1 · Attach student work and the mark scheme</li>
                <li>2 · Describe the assignment</li>
                <li>3 · Start the durable correction job</li>
                <li>4 · Monitor: queued → marking → results</li>
                <li>5 · Review the persisted per-question report</li>
              </ol>`,
            })}
          </div>
        </div>
      </div>
      <div>
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
      </div>
    </div>
    ${modalTemplate({
      id: "modal-remove-file",
      title: "Remove file?",
      description:
        "The file is only removed from this selection. Nothing is deleted from your computer or the server.",
      confirmLabel: "Remove",
      confirmTone: "danger",
    })}
  `;
}

function refreshDynamic(root) {
  const review = root.querySelector("[data-file-review]");
  if (review) review.innerHTML = toHTML(reviewHTML());
  const errors = root.querySelector("[data-file-errors]");
  if (errors) errors.innerHTML = toHTML(errorsHTML());
  const jobs = root.querySelector('[data-section="jobs"]');
  if (jobs) jobs.innerHTML = toHTML(jobsContentHTML());
  const results = root.querySelector('[data-section="results"]');
  if (results) results.innerHTML = toHTML(resultsContentHTML());
  const header = root.querySelector(".page-header__actions");
  if (header) header.innerHTML = toHTML(engineBadge());
}

function stopPolling() {
  if (state.pollTimer !== null) {
    clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }
}

function schedulePoll(root, jobId) {
  stopPolling();
  const mounted = state.mounted;
  state.pollTimer = setTimeout(() => {
    if (mounted !== state.mounted || state.activeJobId !== jobId) return;
    refreshActiveJob(root);
  }, POLL_INTERVAL_MS);
}

function upsertJob(job) {
  const next = state.jobs.filter((candidate) => candidate.job_id !== job.job_id);
  next.unshift(job);
  state.jobs = next.slice(0, 50);
}

async function refreshActiveJob(root) {
  const jobId = state.activeJobId;
  if (!jobId) return;
  try {
    const job = await api.corrections.get(jobId);
    if (state.activeJobId !== jobId) return;
    state.job = job;
    state.pollError = null;
    upsertJob(job);
    if (job.status === "completed") {
      stopPolling();
      if (state.report?.job_id !== job.job_id) {
        try {
          state.report = await api.corrections.report(job.job_id);
          state.reportError = null;
        } catch (err) {
          state.reportError = err?.message || "The stored result could not be read.";
        }
      }
    } else if (job.status === "failed") {
      stopPolling();
      state.report = null;
      state.reportError = null;
    } else {
      schedulePoll(root, jobId);
    }
    refreshDynamic(root);
  } catch (err) {
    if (state.activeJobId !== jobId) return;
    state.pollError = err?.message || "The application server could not be reached.";
    stopPolling();
    refreshDynamic(root);
  }
}

async function selectJob(root, jobId, { updateHash = true } = {}) {
  if (!jobId) return;
  stopPolling();
  state.activeJobId = jobId;
  state.job = null;
  state.report = null;
  state.reportError = null;
  state.pollError = null;
  if (updateHash) setJobHash(jobId);
  refreshDynamic(root);
  await refreshActiveJob(root);
}

async function loadJobs(root, { selectLatest = true } = {}) {
  try {
    const payload = await api.corrections.list({ limit: 50 });
    state.jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
    state.jobsError = null;
    const wanted = jobFromHash();
    if (wanted) {
      await selectJob(root, wanted, { updateHash: false });
      // A direct or refreshed result link should show the stored result, not
      // silently leave the user on the upload form.
      selectTab(root, "results");
    } else if (selectLatest && state.jobs.length && !state.activeJobId) {
      await selectJob(root, state.jobs[0].job_id, { updateHash: false });
    } else {
      refreshDynamic(root);
    }
  } catch (err) {
    state.jobsError = err?.message || "The recent correction jobs could not be read.";
    refreshDynamic(root);
  }
}

function addFiles(root, role, fileList) {
  state.fileErrors = [];
  if (state.maxFileBytes === null) {
    showToast("The upload limit is still loading. Try again in a moment.", { tone: "error" });
    return;
  }
  const target = role === "mark_scheme" ? state.schemeFiles : state.studentFiles;
  let added = 0;
  for (const file of Array.from(fileList)) {
    const typeError = validateFileType(file.name, ACCEPTED_TYPES);
    const sizeError = typeError ? null : validateFileSize(file.size, state.maxFileBytes);
    const error = typeError || sizeError;
    if (error) {
      state.fileErrors.push(`${file.name}: ${error}`);
      continue;
    }
    if (state.studentFiles.length + state.schemeFiles.length >= 12) {
      state.fileErrors.push("At most 12 files can be attached to one correction.");
      break;
    }
    target.push({ id: state.nextId++, name: file.name, size: file.size, file });
    added += 1;
  }
  if (added) {
    state.pendingKey = null;
    state.page = Math.max(1, Math.ceil(state.studentFiles.length / PAGE_SIZE));
    showToast(
      `${added} file${added === 1 ? "" : "s"} added to the draft.`,
      { tone: "success" },
    );
  }
  if (state.fileErrors.length) {
    showToast("Some files were not accepted. See the list for details.", { tone: "error" });
  }
  refreshDynamic(root);
}

function removeFile(root, role, id) {
  if (role === "mark_scheme") {
    state.schemeFiles = state.schemeFiles.filter((file) => file.id !== id);
  } else {
    state.studentFiles = state.studentFiles.filter((file) => file.id !== id);
    const pages = Math.max(1, Math.ceil(state.studentFiles.length / PAGE_SIZE));
    state.page = Math.min(state.page, pages);
  }
  state.pendingKey = null;
  refreshDynamic(root);
}

function buildInstructions() {
  const parts = [];
  if (String(state.context.component || "").trim()) {
    parts.push(`Paper or component: ${state.context.component.trim()}`);
  }
  if (String(state.context.notes || "").trim()) {
    parts.push(state.context.notes.trim());
  }
  return parts.join("\n");
}

function makeIdempotencyKey() {
  try {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  } catch {
    /* fall through */
  }
  return `mc6-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
}

async function startCorrection(root) {
  if (state.submitting) return;
  const issues = draftIssues();
  if (issues.length) {
    state.submitError = issues.join(" ");
    refreshDynamic(root);
    return;
  }

  state.submitting = true;
  state.submitError = null;
  state.pendingKey = state.pendingKey || makeIdempotencyKey();
  refreshDynamic(root);

  const formData = new FormData();
  for (const item of state.studentFiles) formData.append("files", item.file, item.name);
  for (const item of state.schemeFiles) {
    formData.append("mark_scheme_files", item.file, item.name);
  }
  formData.append("assignment_title", state.context.title.trim());
  formData.append("instructions", buildInstructions());
  formData.append("mark_scheme", state.context.markScheme);
  formData.append("feedback_detail", state.options.feedbackDetail);
  if (String(state.options.maxScore || "").trim()) {
    formData.append("max_score", String(state.options.maxScore).trim());
  }

  try {
    const job = await api.corrections.submit(formData, {
      idempotencyKey: state.pendingKey,
    });
    state.pendingKey = null;
    state.submitError = null;
    state.studentFiles = [];
    state.schemeFiles = [];
    state.page = 1;
    state.context.markScheme = "";
    state.activeJobId = job.job_id;
    state.job = job;
    state.report = null;
    state.reportError = null;
    state.pollError = null;
    upsertJob(job);
    setJobHash(job.job_id);
    const fileInputs = root.querySelectorAll("[data-file-input]");
    for (const input of fileInputs) input.value = "";
    const schemeField = root.querySelector("#ctx-mark-scheme");
    if (schemeField) schemeField.value = "";
    selectTab(root, "jobs");
    refreshDynamic(root);
    await refreshActiveJob(root);
  } catch (err) {
    state.submitError = err?.message || "The correction job could not be created.";
    refreshDynamic(root);
  } finally {
    state.submitting = false;
    refreshDynamic(root);
  }
}

async function loadServerSettings(root) {
  const help = root.querySelector('[data-fill="max-upload-help"]');
  const inputs = root.querySelectorAll("[data-file-input]");
  const retry = root.querySelector("[data-upload-limit-retry]");
  if (retry) retry.hidden = true;
  if (help) {
    help.textContent = "PDF, PNG or JPG files. Reading the current upload limit from the server…";
  }
  try {
    const payload = await api.settings.get();
    const mb = resolveUploadLimitMB(payload?.settings);
    if (mb === null) throw new Error("The server did not provide a valid upload limit.");
    state.maxFileBytes = mb * 1024 * 1024;
    state.settingsLoaded = true;
    if (help) {
      help.textContent = `PDF, PNG or JPG files, up to ${mb} MB each. The server validates the bytes again on upload.`;
    }
    for (const input of inputs) input.disabled = false;
    if (payload.settings.default_feedback_detail) {
      state.options.feedbackDetail = payload.settings.default_feedback_detail;
      const select = root.querySelector("#opt-feedback-detail");
      if (select) select.value = state.options.feedbackDetail;
    }
  } catch {
    state.maxFileBytes = null;
    state.settingsLoaded = false;
    for (const input of inputs) input.disabled = true;
    if (retry) retry.hidden = false;
    if (help) {
      help.textContent = "The current upload limit could not be read from the server. Try again.";
    }
  }
  refreshDynamic(root);
}

async function loadEngineStatus(root) {
  try {
    const status = await api.systemStatus();
    state.engine = status?.correction_engine || null;
    state.engineAvailable = Boolean(status?.features?.ai_correction);
    state.jobsAvailable = Boolean(status?.features?.correction_jobs);
  } catch {
    state.engine = null;
    state.engineAvailable = false;
    state.jobsAvailable = false;
  }
  refreshDynamic(root);
}

export function mount(root, { signal } = {}) {
  state.mounted += 1;
  state.activeJobId = null;
  state.job = null;
  state.report = null;
  state.reportError = null;
  state.jobsError = null;
  state.submitError = null;
  state.pollError = null;
  stopPolling();

  initTabs(root, { signal });
  loadServerSettings(root);
  loadEngineStatus(root);
  loadJobs(root);

  root.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const fileInput = target.closest("[data-file-input]");
    if (fileInput) {
      addFiles(root, fileInput.getAttribute("data-file-input"), fileInput.files || []);
      target.value = "";
      return;
    }
    const group = target.getAttribute("data-draft-group");
    const key = target.getAttribute("data-draft-key");
    if (group && key && target instanceof HTMLInputElement) {
      state[group][key] = target.type === "checkbox" ? target.checked : target.value;
      if (group === "options" || group === "context") state.pendingKey = null;
      refreshDynamic(root);
    }
  }, { signal });

  root.addEventListener("input", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const group = target.getAttribute("data-draft-group");
    const key = target.getAttribute("data-draft-key");
    if (
      group &&
      key &&
      (target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement)
    ) {
      state[group][key] = target.value;
      if (group === "options" || group === "context") state.pendingKey = null;
      refreshDynamic(root);
    }
  }, { signal });

  root.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    if (target.closest('[data-action="retry-upload-limit"]')) {
      loadServerSettings(root);
      return;
    }
    if (target.closest('[data-action="retry-jobs"]')) {
      loadJobs(root, { selectLatest: false });
      return;
    }
    if (target.closest('[data-action="refresh-job"]')) {
      refreshActiveJob(root);
      return;
    }
    if (target.closest('[data-action="start-correction"]')) {
      startCorrection(root);
      return;
    }
    if (target.closest('[data-action="view-results"]')) {
      selectTab(root, "results");
      return;
    }

    const openJob = target.closest("[data-open-job]");
    if (openJob) {
      selectJob(root, openJob.getAttribute("data-open-job"));
      selectTab(root, "jobs");
      return;
    }

    const removeBtn = target.closest("[data-remove-file]");
    if (removeBtn) {
      pendingRemove = {
        role: removeBtn.getAttribute("data-file-role") || "submission",
        id: Number(removeBtn.getAttribute("data-remove-file")),
      };
      if (prefs.get("confirmBeforeRemove")) {
        openModal("modal-remove-file", {
          onConfirm: () => {
            if (pendingRemove) removeFile(root, pendingRemove.role, pendingRemove.id);
            pendingRemove = null;
          },
        });
      } else if (pendingRemove) {
        removeFile(root, pendingRemove.role, pendingRemove.id);
        pendingRemove = null;
      }
      return;
    }

    const pageBtn = target.closest("[data-page]");
    if (pageBtn && !pageBtn.hasAttribute("disabled")) {
      const page = Number(pageBtn.getAttribute("data-page"));
      if (Number.isFinite(page) && page >= 1) {
        state.page = page;
        refreshDynamic(root);
      }
    }
  }, { signal });

  signal?.addEventListener(
    "abort",
    () => {
      stopPolling();
    },
    { once: true },
  );
}
