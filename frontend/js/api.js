/* API service layer — the single place the frontend talks to the backend.
 *
 * Future phases add correction, Classroom and report calls here; pages never
 * call fetch() directly, so the integration boundary stays in one module.
 */

export class ApiError extends Error {
  constructor(message) {
    super(message);
    this.name = "ApiError";
  }
}

async function requestJSON(path, { timeout = 10000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(path, {
      signal: controller.signal,
      headers: { Accept: "application/json" },
    });
    if (!res.ok) {
      throw new ApiError(`The server returned an error (HTTP ${res.status}).`);
    }
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
