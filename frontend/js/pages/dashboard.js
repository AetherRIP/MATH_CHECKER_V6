/* Dashboard: an operational console for the correction system.
 *
 * The primary focus is the correction pipeline strip — live queued,
 * processing, completed and failed counters. Counts come from the local
 * database and readiness comes from the server. Nothing here is sample data;
 * loading, empty and error states are real.
 */

import { html, render as toHTML } from "../ui/html.js";
import { pageHeader, card, statCard, detailRows } from "../ui/card.js";
import { button } from "../ui/button.js";
import { badge } from "../ui/badge.js";
import { dataTable } from "../ui/table.js";
import { emptyState, errorState, loadingState } from "../ui/states.js";
import { api } from "../api.js";
import { formatCount } from "../format.js";

const INTEGRATION_SOURCES = 2;

export function readinessRows(status) {
  const database = status.database || {};
  const databaseReady = database.status === "ready";
  const features = status.features || {};
  const engine = status.correction_engine || {};
  const correctionReady = Boolean(features.ai_correction);
  const correctionLabel = !databaseReady
    ? "Unavailable (database)"
    : correctionReady
      ? "Ready"
      : engine.reason
        ? "Unavailable"
        : "Not configured";
  return [
    {
      label: "Application interface",
      value: badge({ label: "Ready", tone: "success", iconName: "check-circle" }),
    },
    {
      label: "Backend API",
      value: badge({ label: "Reachable", tone: "success", iconName: "check-circle" }),
    },
    {
      label: "Database",
      value: databaseReady
        ? badge({
            label: `Ready · schema ${database.schema_version}`,
            tone: "success",
            iconName: "check-circle",
          })
        : badge({ label: "Unavailable", tone: "error" }),
    },
    {
      label: "AI provider",
      value: status.ai_provider_configured
        ? badge({ label: "Configured", tone: "success" })
        : badge({ label: "Not configured", tone: "neutral" }),
    },
    {
      label: "Google Classroom",
      value: status.classroom_configured
        ? badge({ label: "Configured", tone: "success" })
        : badge({ label: "Not configured (planned)", tone: "neutral" }),
    },
    {
      label: "Correction processing",
      value: correctionReady
        ? badge({ label: "Ready", tone: "success", iconName: "check-circle" })
        : badge({ label: correctionLabel, tone: "warning" }),
    },
    {
      label: "Background tasks",
      value: Boolean(features.background_tasks)
        ? badge({ label: "Ready", tone: "success", iconName: "check-circle" })
        : badge({ label: "Unavailable", tone: "warning" }),
    },
  ];
}

export function submissionStatusRows(counts) {
  return [
    { key: "missing", label: "Missing", count: counts.missing },
    { key: "draft", label: "Draft", count: counts.draft },
    { key: "submitted", label: "Submitted", count: counts.submitted },
    { key: "graded", label: "Graded", count: counts.graded },
    { key: "failed", label: "Failed", count: counts.failed },
  ];
}

export function statsHTML(counts) {
  if (!counts || counts.total === 0) {
    return emptyState({
      iconName: "storage",
      title: "No submissions recorded yet",
      description:
        "Students, assignments and submissions appear here as they are added to the local database.",
      compact: true,
    });
  }

  return dataTable({
    caption: "Counts are read from the local database when this page opens.",
    columns: [
      { key: "status", label: "Status" },
      { key: "count", label: "Submissions", numeric: true },
    ],
    rows: submissionStatusRows(counts).map((row) => ({
      key: row.key,
      cells: { status: row.label, count: formatCount(row.count) },
    })),
  });
}

function shortJobId(jobId) {
  const text = String(jobId || "");
  return text.length > 12 ? `${text.slice(0, 8)}…` : text;
}

function jobStatusBadge(status) {
  const tones = { queued: "info", processing: "info", completed: "success", failed: "error" };
  const labels = { queued: "Queued", processing: "Processing", completed: "Completed", failed: "Failed" };
  return badge({ label: labels[status] || status, tone: tones[status] || "neutral" });
}

/** Pipeline strip: the dashboard's primary operational readout. */
export function pipelineHTML(counts) {
  const c = counts || { queued: 0, processing: 0, completed: 0, failed: 0 };
  const stages = [
    { id: "queued", label: "Queued", count: c.queued, note: "Waiting for a slot" },
    { id: "processing", label: "Processing", count: c.processing, note: "Engine marking" },
    { id: "completed", label: "Completed", count: c.completed, note: "Results persisted" },
    { id: "failed", label: "Failed", count: c.failed, note: "Needs attention" },
  ];
  return html`<div class="pipeline" role="list" aria-label="Correction pipeline by job state">
    ${stages.map(
      (stage) => html`<div class="pipeline__stage" role="listitem" data-tone="${stage.id}">
        <span class="pipeline__stage-label"><span class="pipeline__dot"></span>${stage.label}</span>
        <span class="pipeline__count">${formatCount(stage.count)}</span>
        <span class="pipeline__note">${stage.note}</span>
      </div>`,
    )}
  </div>`;
}

export function jobsHTML(jobs) {
  return dataTable({
    columns: [
      { key: "job", label: "Job" },
      { key: "assignment", label: "Assignment" },
      { key: "status", label: "Status" },
      { key: "created", label: "Created" },
      { key: "open", label: "" },
    ],
    rows: (jobs || []).map((job) => ({
      key: job.job_id,
      cells: {
        job: html`<code title="${job.job_id}">${shortJobId(job.job_id)}</code>`,
        assignment: job.assignment_title,
        status: jobStatusBadge(job.status),
        created: job.created_at ? new Date(job.created_at).toLocaleString() : "—",
        open: html`<a class="btn btn--ghost" href="#/correction?job=${encodeURIComponent(job.job_id)}">Open</a>`,
      },
    })),
    empty: {
      iconName: "tasks",
      title: "No correction jobs yet",
      description: "Start a correction from the AI Correction page; jobs and their results are stored locally.",
    },
  });
}

async function loadJobs(root) {
  const section = root.querySelector('[data-section="jobs"]');
  if (section) section.innerHTML = toHTML(loadingState({ label: "Reading recent correction jobs…" }));
  try {
    const payload = await api.corrections.list({ limit: 5 });
    if (section) section.innerHTML = toHTML(jobsHTML(payload.jobs));
  } catch (err) {
    if (section) {
      section.innerHTML = toHTML(
        errorState({
          title: "Recent jobs unavailable",
          description: err?.message || "The application server could not be reached to read correction jobs.",
          actions: button({ label: "Retry", iconName: "refresh", attrs: 'data-action="retry-jobs"' }),
        }),
      );
    }
  }
}

export function render() {
  return html`
    ${pageHeader({
      title: "Dashboard",
      description:
        "Operational overview of the correction system. Counts and readiness are read live from the running backend.",
      actions: html`
        ${button({ label: "New correction", variant: "primary", iconName: "correction", href: "#/correction" })}
        ${button({ label: "Settings", iconName: "settings", href: "#/settings" })}
      `,
    })}

    <section aria-labelledby="stats-heading">
      <h2 id="stats-heading" class="sr-only">Key figures</h2>
      <div class="stat-grid">
        ${statCard({
          label: "Students",
          value: html`<span data-fill="stat-students">—</span>`,
          hint: "Stored in the local database",
        })}
        ${statCard({
          label: "Assignments",
          value: html`<span data-fill="stat-assignments">—</span>`,
          hint: "Including chapter and lesson codes",
          tone: "info",
        })}
        ${statCard({
          label: "Submissions",
          value: html`<span data-fill="stat-submissions">—</span>`,
          hint: html`<span data-fill="stat-submissions-hint">Loading…</span>`,
          tone: "success",
        })}
        ${statCard({
          label: "Integrations configured",
          value: html`<span data-fill="integrations">—</span>`,
          hint: "AI provider and Google Classroom",
          tone: "warning",
        })}
      </div>
    </section>

    <div class="stack">
      ${card({
        title: "Correction pipeline",
        description: "Durable job states read from the local database.",
        body: html`
          <div data-section="pipeline">${loadingState({ label: "Reading pipeline counters…" })}</div>
          <div class="mt-4" data-section="jobs">${loadingState({ label: "Reading recent correction jobs…" })}</div>
        `,
      })}

      <div class="grid-2">
        ${card({
          title: "Submissions by status",
          description: "Live counts of student work recorded in the local database.",
          actions: button({ label: "Refresh", iconName: "refresh", attrs: 'data-action="retry-stats"' }),
          body: html`<div data-section="stats">${loadingState({ label: "Reading database statistics…" })}</div>`,
        })}
        ${card({
          title: "Application readiness",
          description: "Live status of the application and its integrations.",
          actions: button({ label: "Refresh", iconName: "refresh", attrs: 'data-action="retry-status"' }),
          body: html`
            <div data-section="readiness">${loadingState({ label: "Reading application status…" })}</div>
            <p class="field__help mt-4">
              Status is read from the server when this page opens. Nothing on this page is sample data.
            </p>
          `,
        })}
      </div>

      ${card({
        title: "Quick actions",
        description: "Jump straight to a workspace.",
        body: html`
          <div class="row">
            ${button({ label: "New correction", variant: "primary", iconName: "correction", href: "#/correction" })}
            ${button({ label: "Manage storage", iconName: "storage", href: "#/storage" })}
            ${button({ label: "Task manager", iconName: "tasks", href: "#/tasks" })}
          </div>
        `,
      })}
    </div>
  `;
}

function setText(root, selector, value) {
  const element = root.querySelector(selector);
  if (element) element.textContent = value;
}

async function loadStats(root) {
  const section = root.querySelector('[data-section="stats"]');
  if (section) section.innerHTML = toHTML(loadingState({ label: "Reading database statistics…" }));

  try {
    const data = await api.databaseStats();
    const counts = data.counts;
    setText(root, '[data-fill="stat-students"]', formatCount(counts.students));
    setText(root, '[data-fill="stat-assignments"]', formatCount(counts.assignments));
    setText(root, '[data-fill="stat-submissions"]', formatCount(counts.submissions.total));
    setText(
      root,
      '[data-fill="stat-submissions-hint"]',
      `${counts.submissions.missing} missing · ${counts.submissions.draft} drafts · ${counts.submissions.graded} graded`,
    );
    if (section) section.innerHTML = toHTML(statsHTML(counts.submissions));
  } catch (err) {
    for (const selector of ['[data-fill="stat-students"]', '[data-fill="stat-assignments"]', '[data-fill="stat-submissions"]']) {
      setText(root, selector, "—");
    }
    setText(root, '[data-fill="stat-submissions-hint"]', "Statistics unavailable");
    if (section) {
      section.innerHTML = toHTML(
        errorState({
          title: "Database statistics unavailable",
          description:
            err?.message ||
            "The application server could not be reached to read the local database.",
          actions: button({ label: "Retry", iconName: "refresh", attrs: 'data-action="retry-stats"' }),
        }),
      );
    }
  }
}

/** Derive pipeline stage counters from the full job list. */
export function pipelineCounts(jobs) {
  const counts = { queued: 0, processing: 0, completed: 0, failed: 0 };
  for (const job of jobs || []) {
    if (job.status in counts) counts[job.status] += 1;
  }
  return counts;
}

async function loadPipeline(root) {
  const section = root.querySelector('[data-section="pipeline"]');
  if (section) section.innerHTML = toHTML(loadingState({ label: "Reading pipeline counters…" }));
  try {
    const payload = await api.corrections.list({ limit: 50 });
    if (section) section.innerHTML = toHTML(pipelineHTML(pipelineCounts(payload.jobs)));
  } catch {
    if (section) {
      section.innerHTML = toHTML(
        errorState({
          title: "Pipeline unavailable",
          description: "The application server could not be reached to read correction job states.",
          actions: button({ label: "Retry", iconName: "refresh", attrs: 'data-action="retry-jobs"' }),
        }),
      );
    }
  }
}

async function loadReadiness(root) {
  const section = root.querySelector('[data-section="readiness"]');
  const fill = root.querySelector('[data-fill="integrations"]');
  try {
    const status = await api.systemStatus();
    const configured =
      (status.ai_provider_configured ? 1 : 0) + (status.classroom_configured ? 1 : 0);
    if (fill) fill.textContent = `${configured} of ${INTEGRATION_SOURCES}`;
    if (section) section.innerHTML = toHTML(detailRows(readinessRows(status)));
  } catch (err) {
    if (fill) fill.textContent = "—";
    if (section) {
      section.innerHTML = toHTML(
        errorState({
          title: "Status unavailable",
          description: "The application server could not be reached to read the current status.",
          actions: button({ label: "Retry", iconName: "refresh", attrs: 'data-action="retry-status"' }),
        }),
      );
    }
  }
}

export function mount(root, { signal } = {}) {
  loadStats(root);
  loadReadiness(root);
  loadPipeline(root);
  loadJobs(root);
  root.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest('[data-action="retry-stats"]')) {
      loadStats(root);
    }
    if (target.closest('[data-action="retry-status"]')) {
      loadReadiness(root);
    }
    if (target.closest('[data-action="retry-jobs"]')) {
      loadPipeline(root);
      loadJobs(root);
    }
  }, { signal });
}
