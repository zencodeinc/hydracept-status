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

/**
 * Stale when probe data age exceeds stale_after_seconds.
 * Never uses probe-written timestamps as "now" (they track last check, not wall clock).
 */
export function isProbeStale(doc, clientNowMs, responseDateMs) {
  const generated = parseIso(doc?.generated_at);
  const staleAfterMs = (doc?.stale_after_seconds || 900) * 1000;
  if (!generated) return true;
  const { referenceMs } = referenceNowMs(clientNowMs, responseDateMs);
  const ageMs = referenceMs - generated.getTime();
  if (ageMs < -60_000) {
    return true;
  }
  return ageMs > staleAfterMs;
}

export function probeDataAgeSeconds(doc, clientNowMs, responseDateMs) {
  const generated = parseIso(doc?.generated_at);
  if (!generated) return null;
  const { referenceMs } = referenceNowMs(clientNowMs, responseDateMs);
  return Math.max(0, Math.floor((referenceMs - generated.getTime()) / 1000));
}

/** Never show operational when stale; never upgrade stored failure states. */
export function displayComponentStatus(storedStatus, stale) {
  if (stale) return "unknown";
  const stored = storedStatus || "unknown";
  return stored;
}

export function formatUptimeLabel(row) {
  if (row?.history_collecting) {
    return "collecting data";
  }
  if (row?.uptime_percent_90d == null) {
    return "collecting data";
  }
  return `${row.uptime_percent_90d}%`;
}

export function pageViewModel(doc, clientNowMs, responseDateMs) {
  const { clockSource } = referenceNowMs(clientNowMs, responseDateMs);
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
  return {
    stale,
    overall: displayComponentStatus(doc?.overall || "unknown", stale),
    components: rendered,
    clockSource,
    dataAgeSeconds,
    stateRecovered: Boolean(doc?.state_recovered),
  };
}
