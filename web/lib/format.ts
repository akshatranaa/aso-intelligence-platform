/** Shared date-formatting helpers. */

/**
 * Parse a backend timestamp, treating a timezone-less value as UTC.
 *
 * The API stores `datetime.now().isoformat()` — a naive timestamp with no
 * offset (e.g. "2026-07-15T19:37:51"), which on the UTC server is UTC. JS parses
 * a tz-less datetime string as *browser-local* time, which would shift every
 * value by the viewer's UTC offset (e.g. "just collected" → "6 hours ago" in
 * India). Appending "Z" when no offset is present pins it to UTC.
 */
function parseUtc(iso: string): Date {
  const hasTz = /(?:Z|[+-]\d\d:?\d\d)$/.test(iso);
  return new Date(hasTz ? iso : iso + "Z");
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = parseUtc(iso);
  return isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** "3 days ago", "just now", "2 months ago" — falls back to fmtDate for older dates. */
export function fmtRelativeDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = parseUtc(iso);
  if (isNaN(d.getTime())) return "—";
  const seconds = Math.round((Date.now() - d.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  return fmtDate(iso);
}
