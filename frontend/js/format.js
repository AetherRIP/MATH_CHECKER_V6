/* Pure formatting helpers shared across pages (unit-tested in Node). */

export function formatBytes(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value < 0) return "—";
  if (value === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  const digits = unit === 0 ? 0 : size < 10 ? 1 : 0;
  return `${size.toFixed(digits)} ${units[unit]}`;
}

export function formatCount(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString("en-GB") : "—";
}
