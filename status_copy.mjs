/** User-facing copy for status.hydracept.com (tested in Node; no DOM). */

export const PAGE_TAGLINE =
  "We probe the public API, website, Studio, docs, hosted MCP endpoints, and capability list every few minutes.";

export const INCIDENTS_EMPTY = "No incidents posted.";

export const LOAD_FAILURE_MESSAGE =
  "We couldn't load status data right now. Try reloading the page; if this keeps happening, the status page itself may be having trouble.";

export const NOSCRIPT_MESSAGE =
  "Live status needs JavaScript. Visit hydracept.com for the product site, or the docs for integration help.";

export const SHELL_WITHOUT_JS_MESSAGE = NOSCRIPT_MESSAGE;

export function overallPillLabel(status) {
  if (status === "operational") return "All checks passing";
  if (status === "degraded") return "Some issues";
  if (status === "down") return "Outage";
  return "No recent data";
}

export function componentPillLabel(status) {
  if (status === "operational") return "Up";
  if (status === "degraded") return "Degraded";
  if (status === "down") return "Outage";
  return "No recent data";
}

/** @deprecated use overallPillLabel / componentPillLabel */
export function statusPillLabel(status) {
  return overallPillLabel(status);
}

export function formatAge(seconds) {
  if (seconds == null) return "a while";
  if (seconds < 120) return `${seconds} seconds`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 120) return `${minutes} minutes`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} hours`;
  const days = Math.floor(hours / 24);
  return `${days} days`;
}

export function clockSuffix(clockSource) {
  if (clockSource === "client-fallback") {
    return " (using your browser clock because the response had no Date header)";
  }
  return "";
}

export function overallSummary(view, doc, formatWhen) {
  const clock = clockSuffix(view.clockSource);
  if (view.timestampSkewed) {
    return `The timestamp on this report looks wrong, so we can't trust it. Treat everything as unknown until a fresh check arrives${clock}.`;
  }
  if (view.stateRecovered) {
    return `Our saved check history was unreadable, so we started it over. Older history may be missing. Last successful check was ${formatWhen(doc.generated_at)}.`;
  }
  if (view.stale) {
    const age = formatAge(view.dataAgeSeconds);
    return `Our monitors haven't reported in ${age}${clock}. We can't tell if things are healthy right now. Last successful check was ${formatWhen(doc.generated_at)}.`;
  }
  const age = formatAge(view.dataAgeSeconds);
  const interval = doc.probe_interval_seconds || 300;
  const staleAfter = doc.stale_after_seconds || 900;
  return `Latest probe results from ${formatWhen(doc.generated_at)} (${age} ago). Checks run about every ${Math.round(interval / 60)} minutes; we mark data stale after ${Math.round(staleAfter / 60)} minutes without an update.`;
}

export function historyRangeLabel(historyDays, formatShortDate) {
  const days = Array.isArray(historyDays) ? historyDays : [];
  if (!days.length) return null;
  const first = days[0]?.date;
  if (!first) return null;
  return `Since ${formatShortDate(first)}`;
}

export function componentStatusLine(row, formatWhen, uptimeLabel, { stale = false } = {}) {
  const detail = (row.detail || "No detail from the last check").trim();
  const parts = [];
  if (stale) {
    parts.push(`Last result: ${detail}`);
  } else {
    parts.push(detail);
    parts.push(`Checked ${formatWhen(row.last_checked_at)}`);
  }
  if (uptimeLabel != null && uptimeLabel !== "") {
    parts.push(`90-day uptime ${uptimeLabel}`);
  }
  return parts.join(". ") + ".";
}
