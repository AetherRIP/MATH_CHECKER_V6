/* API service layer — the single place the frontend talks to the backend.
 *
 * Pages never call fetch() directly. Every request shares one error shape:
 * a backend error envelope's message is surfaced when present, otherwise a
 * short, user-safe fallback is used.
 */

export class ApiError extends Error {
  constructor(message, { status = 0, code = "" } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export async function requestJSON(path, { method = "GET", body, timeout = 10000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const headers = { Accept: "application/json" };
  const init = { method, signal: controller.signal, headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  try {
    const res = await fetch(path, init);
    if (!res.ok) {
      let message = `The server returned an error (HTTP ${res.status}).`;
      let code = "";
      try {
        const payload = await res.json();
        if (payload && payload.error && typeof payload.error.message === "string") {
          message = payload.error.message;
          code = typeof payload.error.code === "string" ? payload.error.code : "";
        }
      } catch {
        /* Non-JSON error body: keep the generic HTTP message. */
      }
      throw new ApiError(message, { status: res.status, code });
    }
    if (res.status === 204) return null;
    return await res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err && err.name === "AbortError") {
      throw new ApiError("The request timed out.");
    }
    throw new ApiError("Could not reach the application server.");
  } finally {
    clearTimeout(timer);
  }
}

// The system status is fetched once and shared: the top bar, Dashboard and
// Settings all read the same response instead of issuing repeat requests.
let statusPromise = null;

export const api = {
  health: () => requestJSON("/api/health"),
  storageSummary: () => requestJSON("/api/storage/summary"),
  databaseStats: () => requestJSON("/api/database/stats"),
  settings: {
    get: () => requestJSON("/api/settings"),
    update: (changes) => requestJSON("/api/settings", { method: "PATCH", body: changes }),
  },
  systemStatus() {
    if (!statusPromise) {
      statusPromise = requestJSON("/api/system/status").catch((err) => {
        statusPromise = null;
        throw err;
      });
    }
    return statusPromise;
  },
};
