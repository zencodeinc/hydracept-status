/** Hydracept public status page — reads probe JSON only; never upgrades status client-side. */

import {
  displayComponentStatus,
  formatUptimeLabel,
  isProbeStale,
  pageViewModel,
  parseIso,
} from "./status_display.mjs";

const STATUS_URL = "./status.json";
const INCIDENTS_URL = "./incidents.json";

function statusClass(status) {
  if (status === "operational") return "operational";
  if (status === "degraded") return "degraded";
  if (status === "down") return "down";
  return "unknown";
}

function historyBarClass(day) {
  const ratio = Number(day.uptime_ratio);
  if (ratio >= 0.995) return "up";
  if (ratio <= 0.01) return "down";
  return "partial";
}

function formatWhen(iso) {
  const d = parseIso(iso);
  if (!d) return "unknown time";
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function renderHistory(historyDays) {
  const bar = document.createElement("div");
  bar.className = "history";
  bar.setAttribute("aria-hidden", "true");
  const days = Array.isArray(historyDays) ? historyDays : [];
  for (const day of days.slice(-90)) {
    const cell = document.createElement("span");
    cell.className = historyBarClass(day);
    cell.title = `${day.date}: ${Math.round(Number(day.uptime_ratio || 0) * 1000) / 10}% checks ok`;
    bar.append(cell);
  }
  return bar;
}

function renderComponents(view) {
  const root = document.getElementById("components");
  root.replaceChildren();
  for (const [key, row] of Object.entries(view.components)) {
    try {
      const shown = row.displayed_status;
      const card = document.createElement("article");
      card.className = "component";
      card.dataset.component = key;
      card.dataset.storedStatus = row.status || "unknown";
      const head = document.createElement("div");
      head.className = "component-head";
      const name = document.createElement("div");
      name.className = "component-name";
      name.textContent = row.display_name || key;
      const pill = document.createElement("span");
      pill.className = `pill ${statusClass(shown)}`;
      pill.textContent = shown;
      pill.dataset.status = shown;
      head.append(name, pill);
      const detail = document.createElement("div");
      detail.className = "component-detail";
      detail.textContent = `${row.detail || ""} · Last checked ${formatWhen(row.last_checked_at)} · 90d uptime ${formatUptimeLabel(row)}`;
      card.append(head, detail, renderHistory(row.history_days));
      root.append(card);
    } catch (componentErr) {
      const fallback = document.createElement("article");
      fallback.className = "component";
      fallback.dataset.component = key;
      fallback.textContent = `${key}: unable to render (${componentErr.message || componentErr})`;
      root.append(fallback);
    }
  }
}

function renderIncidents(payload) {
  const root = document.getElementById("incidents-list");
  root.replaceChildren();
  const incidents = (payload && payload.incidents) || [];
  if (!incidents.length) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = "No incidents recorded.";
    root.append(p);
    return;
  }
  for (const item of incidents) {
    const block = document.createElement("article");
    block.className = "incident";
    const title = document.createElement("h3");
    title.textContent = item.title || "Incident";
    const when = document.createElement("time");
    when.textContent = `${item.status || "unknown"} · started ${formatWhen(item.started_at)}`;
    block.append(title, when);
    if (Array.isArray(item.updates)) {
      const list = document.createElement("ul");
      list.className = "updates";
      for (const update of item.updates) {
        const li = document.createElement("li");
        li.textContent = `${formatWhen(update.at)} — ${update.body || ""}`;
        list.append(li);
      }
      block.append(list);
    }
    root.append(block);
  }
}

function formatAge(seconds) {
  if (seconds == null) return "unknown age";
  if (seconds < 120) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 120) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function renderOverall(view, doc) {
  const pill = document.getElementById("overall-pill");
  pill.className = `pill ${statusClass(view.overall)}`;
  pill.textContent = view.overall;
  pill.dataset.status = view.overall;
  const meta = document.getElementById("overall-meta");
  const agePart = `Data age ${formatAge(view.dataAgeSeconds)}`;
  const clockPart =
    view.clockSource === "client-fallback" ? " (using browser clock — HTTP Date header missing)" : "";
  if (view.stateRecovered) {
    meta.textContent = `Probe state was reset after a corrupt file (${doc.state_recovery?.reason || "recovery"}). ${agePart}${clockPart}.`;
  } else if (view.stale) {
    meta.textContent = `Probe data is stale (${agePart}${clockPart}). Last success ${formatWhen(doc.generated_at)}. Treat all components as unknown.`;
  } else {
    meta.textContent = `Last probe ${formatWhen(doc.generated_at)} · ${agePart} · interval ${doc.probe_interval_seconds || 300}s · stale after ${doc.stale_after_seconds || 900}s`;
  }
}

async function loadJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${url} HTTP ${res.status}`);
  const responseDateMs = Date.parse(res.headers.get("Date") || "") || null;
  const payload = await res.json();
  return { payload, responseDateMs };
}

async function main() {
  const banner = document.getElementById("error-banner");
  try {
    const { payload: statusDoc, responseDateMs } = await loadJson(STATUS_URL);
    const { payload: incidentsDoc } = await loadJson(INCIDENTS_URL);
    const view = pageViewModel(statusDoc, Date.now(), responseDateMs);
    renderOverall(view, statusDoc);
    renderComponents(view);
    renderIncidents(incidentsDoc);
  } catch (err) {
    banner.hidden = false;
    banner.textContent = `Unable to load status data: ${err.message || err}`;
  }
}

main();
