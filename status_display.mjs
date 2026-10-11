/** Pure status page display rules (shared by app.js and Node tests). */

export function parseIso(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Reference clock for staleness: HTTP Date on status.json fetch, else client (flagged). */
export function referenceNowMs(clientNowMs, responseDateMs) {
  if (responseDateMs != null && !Number.isNaN(responseDateMs)) {
    return { referenceMs: responseDateMs, clockSource: "http-date" };
  }
  return { referenceMs: clientNowMs, clockSource: "client-fallback" };
}

export function probeAgeMs(doc, clientNowMs, responseDateMs) {
  const generated = parseIso(doc?.generated_at);
  if (!generated) return null;
  const { referenceMs } = referenceNowMs(clientNowMs, responseDateMs);
  return referenceMs - generated.getTime();
}

/** Future or missing generated_at — fail closed, do not show "0 seconds ago". */
export function isTimestampSkewed(doc, clientNowMs, responseDateMs) {
  if (!doc?.generated_at) return true;
  const ageMs = probeAgeMs(doc, clientNowMs, responseDateMs);
  if (ageMs == null) return true;
  return ageMs < -60_000;
}

/**
 * Stale when probe data age exceeds stale_after_seconds.
 * Never uses probe-written timestamps as "now" (they track last check, not wall clock).
 */
export function isProbeStale(doc, clientNowMs, responseDateMs) {
  if (!doc?.generated_at) return true;
  if (isTimestampSkewed(doc, clientNowMs, responseDateMs)) return true;
  const staleAfterMs = (doc?.stale_after_seconds || 900) * 1000;
  const ageMs = probeAgeMs(doc, clientNowMs, responseDateMs);
  return ageMs != null && ageMs > staleAfterMs;
}

export function probeDataAgeSeconds(doc, clientNowMs, responseDateMs) {
  if (isTimestampSkewed(doc, clientNowMs, responseDateMs)) return null;
  const ageMs = probeAgeMs(doc, clientNowMs, responseDateMs);
  if (ageMs == null) return null;
  return Math.max(0, Math.floor(ageMs / 1000));
}

/** Never show operational when stale; never upgrade stored failure states. */
export function displayComponentStatus(storedStatus, stale) {
  if (stale) return "unknown";
  const stored = storedStatus || "unknown";
  return stored;
}

/** Floor to one decimal so 99.996% never displays as 100.0%. */
export function formatUptimePercent(raw) {
  const n = Number(raw);
  if (Number.isNaN(n)) return null;
  const floored = Math.floor(n * 10) / 10;
  if (floored >= 100 && n < 100) {
    return `${Math.floor(n * 10) / 10}%`;
  }
  if (Number.isInteger(floored)) {
    return `${floored}%`;
  }
  return `${floored.toFixed(1)}%`;
}

/** Returns null when there is not enough history to show a percentage yet. */
export function formatUptimeLabel(row) {
  if (row?.history_collecting) {
    return null;
  }
  if (row?.uptime_percent_90d == null) {
    return null;
  }
  return formatUptimePercent(row.uptime_percent_90d);
}

export function pageViewModel(doc, clientNowMs, responseDateMs) {
  const { clockSource } = referenceNowMs(clientNowMs, responseDateMs);
  const timestampSkewed = isTimestampSkewed(doc, clientNowMs, responseDateMs);
  const stale = isProbeStale(doc, clientNowMs, responseDateMs);
  const dataAgeSeconds = probeDataAgeSeconds(doc, clientNowMs, responseDateMs);
  const components = doc?.components || {};
  const rendered = {};
  for (const [key, row] of Object.entries(components)) {
    const stored = row?.status || "unknown";
    rendered[key] = {
      ...row,
      displayed_status: displayComponentStatus(stored, stale),
    };
  }
  let overall = displayComponentStatus(doc?.overall || "unknown", stale);
  if (timestampSkewed) {
    overall = "unknown";
  }
  return {
    stale,
    timestampSkewed,
    overall,
    components: rendered,
    clockSource,
    dataAgeSeconds,
    stateRecovered: Boolean(doc?.state_recovered) && !timestampSkewed,
  };
}
