import { test } from "node:test";
import assert from "node:assert/strict";

import { api, ApiError, requestJSON } from "../js/api.js";

const originalFetch = globalThis.fetch;

async function withFetch(stub, fn) {
  globalThis.fetch = stub;
  try {
    return await fn();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

test("settings.get sends a GET request with JSON accept headers", async () => {
  const calls = [];
  await withFetch(
    async (path, init) => {
      calls.push({ path, init });
      return jsonResponse({ settings: { max_upload_mb: 25, default_feedback_detail: "detailed" } });
    },
    async () => {
      const payload = await api.settings.get();
      assert.equal(payload.settings.max_upload_mb, 25);
    },
  );

  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, "/api/settings");
  assert.equal(calls[0].init.method, "GET");
  assert.equal(calls[0].init.headers.Accept, "application/json");
  assert.equal(calls[0].init.body, undefined);
});

test("settings.update sends a PATCH request with a JSON body", async () => {
  const calls = [];
  await withFetch(
    async (path, init) => {
      calls.push({ path, init });
      return jsonResponse({ settings: { max_upload_mb: 10, default_feedback_detail: "brief" } });
    },
    async () => {
      const payload = await api.settings.update({
        max_upload_mb: 10,
        default_feedback_detail: "brief",
      });
      assert.equal(payload.settings.max_upload_mb, 10);
    },
  );

  assert.equal(calls[0].path, "/api/settings");
  assert.equal(calls[0].init.method, "PATCH");
  assert.equal(calls[0].init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    max_upload_mb: 10,
    default_feedback_detail: "brief",
  });
});

test("databaseStats reads the expected endpoint", async () => {
  const calls = [];
  await withFetch(
    async (path, init) => {
      calls.push({ path, init });
      return jsonResponse({ counts: { students: 0 } });
    },
    async () => {
      const payload = await api.databaseStats();
      assert.equal(payload.counts.students, 0);
    },
  );
  assert.equal(calls[0].path, "/api/database/stats");
  assert.equal(calls[0].init.method, "GET");
});

test("backend error envelopes are surfaced with code and status", async () => {
  await withFetch(
    async () =>
      jsonResponse(
        { error: { code: "invalid_request", message: "max_upload_mb must be at least 1." } },
        422,
      ),
    async () => {
      await assert.rejects(
        () => api.settings.update({ max_upload_mb: 0 }),
        (error) => {
          assert.ok(error instanceof ApiError);
          assert.equal(error.message, "max_upload_mb must be at least 1.");
          assert.equal(error.code, "invalid_request");
          assert.equal(error.status, 422);
          return true;
        },
      );
    },
  );
});

test("non-JSON error responses fall back to a generic HTTP message", async () => {
  await withFetch(
    async () => ({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error("not json");
      },
    }),
    async () => {
      await assert.rejects(() => api.health(), (error) => {
        assert.ok(error instanceof ApiError);
        assert.match(error.message, /HTTP 500/);
        assert.equal(error.status, 500);
        return true;
      });
    },
  );
});

test("network failures produce a user-safe message", async () => {
  await withFetch(
    async () => {
      throw new TypeError("fetch failed");
    },
    async () => {
      await assert.rejects(() => api.health(), (error) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.message, "Could not reach the application server.");
        return true;
      });
    },
  );
});

test("correction submission posts multipart data with an idempotency key", async () => {
  const calls = [];
  const formData = new FormData();
  formData.append("files", new Blob(["%PDF-1.7"]), "work.pdf");
  formData.append("assignment_title", "Chapter 4");

  await withFetch(
    async (path, init) => {
      calls.push({ path, init });
      return jsonResponse({ job_id: "job-123", status: "queued" }, 202);
    },
    async () => {
      const payload = await api.corrections.submit(formData, {
        idempotencyKey: "browser-request-0001",
      });
      assert.equal(payload.job_id, "job-123");
    },
  );

  assert.equal(calls[0].path, "/api/corrections");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.body, formData);
  assert.equal(calls[0].init.headers["Idempotency-Key"], "browser-request-0001");
  assert.equal(calls[0].init.headers["Content-Type"], undefined);
  assert.equal(calls[0].init.headers.Accept, "application/json");
});

test("correction list, status and report calls use the expected endpoints", async () => {
  const calls = [];
  await withFetch(
    async (path, init) => {
      calls.push({ path, init });
      return jsonResponse({ jobs: [] });
    },
    async () => {
      await api.corrections.list({ limit: 5 });
      await api.corrections.get("job/with space");
      await api.corrections.report("job-123");
    },
  );

  assert.equal(calls[0].path, "/api/corrections?limit=5");
  assert.equal(calls[0].init.method, "GET");
  assert.equal(calls[1].path, "/api/corrections/job%2Fwith%20space");
  assert.equal(calls[2].path, "/api/corrections/job-123/report");
  assert.equal(calls[2].init.method, "GET");
});

test("a not-ready report surfaces the backend message and code", async () => {
  await withFetch(
    async () =>
      jsonResponse(
        {
          error: {
            code: "report_not_ready",
            message: "The correction has not completed, so no result is available.",
          },
        },
        409,
      ),
    async () => {
      await assert.rejects(() => api.corrections.report("job-queued"), (error) => {
        assert.equal(error.code, "report_not_ready");
        assert.equal(error.status, 409);
        assert.match(error.message, /has not completed/);
        return true;
      });
    },
  );
});

test("aborted requests report a timeout", async () => {
  await withFetch(
    async () => {
      const error = new Error("aborted");
      error.name = "AbortError";
      throw error;
    },
    async () => {
      await assert.rejects(() => requestJSON("/api/health", { timeout: 5 }), (error) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.message, "The request timed out.");
        return true;
      });
    },
  );
});
