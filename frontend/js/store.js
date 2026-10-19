/* UI preference store (localStorage). Harmless interface preferences only —
 * never server configuration, credentials or user data.
 *
 * Parsing is total: unknown keys and invalid values fall back to defaults, so
 * a corrupted or hand-edited entry can never break the interface.
 */

export const DEFAULT_PREFS = {
  startPage: "/dashboard",
  density: "comfortable",
  confirmBeforeRemove: true,
  sidebarCollapsed: false,
};

export const START_PAGE_OPTIONS = [
  "/dashboard",
  "/correction",
  "/storage",
  "/tasks",
  "/settings",
];

export function parsePrefs(text) {
  const out = { ...DEFAULT_PREFS };
  if (typeof text !== "string" || !text.trim()) return out;
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    return out;
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) return out;
  if (START_PAGE_OPTIONS.includes(data.startPage)) out.startPage = data.startPage;
  if (data.density === "comfortable" || data.density === "compact") out.density = data.density;
  if (typeof data.confirmBeforeRemove === "boolean") out.confirmBeforeRemove = data.confirmBeforeRemove;
  if (typeof data.sidebarCollapsed === "boolean") out.sidebarCollapsed = data.sidebarCollapsed;
  return out;
}

export function serializePrefs(prefs) {
  return JSON.stringify({ ...DEFAULT_PREFS, ...prefs });
}

export function createStore(storage, key = "mc6.prefs") {
  let memory = null;

  function read() {
    try {
      return parsePrefs(storage ? storage.getItem(key) : memory);
    } catch {
      return { ...DEFAULT_PREFS };
    }
  }

  function write(text) {
    memory = text;
    try {
      if (storage) storage.setItem(key, text);
    } catch {
      /* storage unavailable (private mode, quota) — memory copy still works */
    }
  }

  return {
    getAll: () => read(),
    get: (name) => read()[name],
    set(name, value) {
      write(serializePrefs({ ...read(), [name]: value }));
      return read();
    },
    setAll(partial) {
      write(serializePrefs({ ...read(), ...partial }));
      return read();
    },
    reset() {
      write(serializePrefs(DEFAULT_PREFS));
      return read();
    },
  };
}

function safeLocalStorage() {
  try {
    return typeof localStorage !== "undefined" ? localStorage : null;
  } catch {
    return null;
  }
}

export const prefs = createStore(safeLocalStorage());
