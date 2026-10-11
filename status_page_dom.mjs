/** DOM rendering and bootstrap (testable with linkedom + stub fetch). */

import {
  INCIDENTS_EMPTY,
  LOAD_FAILURE_MESSAGE,
  PAGE_TAGLINE,
  componentPillLabel,
  componentStatusLine,
  historyRangeLabel,
  overallPillLabel,
  overallSummary,
} from "./status_copy.mjs";
import { formatUptimeLabel, pageViewModel, parseIso } from "./status_display.mjs";

export function statusClass(status) {
  if (status === "operational") return "operational";
  if (status === "degraded") return "degraded";
  if (status === "down") return "down";
  return "unknown";
}

export function historyBarClass(day) {
  const ratio = Number(day.uptime_ratio);
  if (ratio >= 0.995) return "up";
  if (ratio <= 0.01) return "down";
  return "partial";
}

export function formatWhen(iso) {
  const d = parseIso(iso);
  if (!d) return "time unknown";
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatShortDate(isoDate) {
  const d = parseIso(isoDate.includes("T") ? isoDate : `${isoDate}T12:00:00.000Z`);
  if (!d) return isoDate;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function renderHistory(document, historyDays) {
  const wrap = document.createElement("div");
  wrap.className = "history-wrap";
  const days = Array.isArray(historyDays) ? historyDays : [];
  const label = historyRangeLabel(days, formatShortDate);
  if (label) {
    const cap = document.createElement("div");
    cap.className = "history-label";
    cap.textContent = label;
    wrap.append(cap);
  }
  const bar = document.createElement("div");
  bar.className = "history";
  bar.setAttribute("aria-hidden", "true");
  for (const day of days.slice(-90)) {
    const cell = document.createElement("span");
    cell.className = historyBarClass(day);
    cell.title = `${day.date}: ${Math.round(Number(day.uptime_ratio || 0) * 1000) / 10}% checks ok`;
    bar.append(cell);
  }
  if (days.length) {
    wrap.append(bar);
  }
  return wrap;
}

export function renderComponents(document, view) {
  const root = document.getElementById("components");
  root.replaceChildren();
  for (const [key, row] of Object.entries(view.components)) {
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
    pill.textContent = componentPillLabel(shown);
    pill.dataset.status = shown;
    head.append(name, pill);
    const detail = document.createElement("div");
    detail.className = "component-detail";
    detail.textContent = componentStatusLine(row, formatWhen, formatUptimeLabel(row), {
      stale: view.stale || view.timestampSkewed,
    });
    card.append(head, detail, renderHistory(document, row.history_days));
    root.append(card);
  }
}

export function renderIncidents(document, payload) {
  const root = document.getElementById("incidents-list");
  root.replaceChildren();
  const incidents = (payload && payload.incidents) || [];
  if (!incidents.length) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = INCIDENTS_EMPTY;
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

export function renderOverall(document, view, doc) {
  const pill = document.getElementById("overall-pill");
  pill.className = `pill ${statusClass(view.overall)}`;
  pill.textContent = overallPillLabel(view.overall);
  pill.dataset.status = view.overall;
  const meta = document.getElementById("overall-meta");
  meta.textContent = overallSummary(view, doc, formatWhen);
}

export function renderLoadFailure(document) {
  const pill = document.getElementById("overall-pill");
  pill.className = "pill unknown";
  pill.textContent = overallPillLabel("unknown");
  pill.dataset.status = "unknown";
  const meta = document.getElementById("overall-meta");
  meta.textContent = LOAD_FAILURE_MESSAGE;
  const banner = document.getElementById("error-banner");
  banner.hidden = false;
  banner.textContent = LOAD_FAILURE_MESSAGE;
  const root = document.getElementById("components");
  root.replaceChildren();
  const incidents = document.getElementById("incidents-list");
  incidents.replaceChildren();
}

export async function bootstrapStatusPage(document, fetchImpl, nowMs = Date.now()) {
  const tagline = document.getElementById("page-tagline");
  tagline.textContent = PAGE_TAGLINE;
  const STATUS_URL = "./status.json";
  const INCIDENTS_URL = "./incidents.json";

  async function loadJson(url) {
    const res = await fetchImpl(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`http-${res.status}`);
    const responseDateMs = Date.parse(res.headers.get("Date") || "") || null;
    const payload = await res.json();
    return { payload, responseDateMs };
  }

  try {
    const { payload: statusDoc, responseDateMs } = await loadJson(STATUS_URL);
    const { payload: incidentsDoc } = await loadJson(INCIDENTS_URL);
    const view = pageViewModel(statusDoc, nowMs, responseDateMs);
    renderOverall(document, view, statusDoc);
    renderComponents(document, view);
    renderIncidents(document, incidentsDoc);
  } catch {
    renderLoadFailure(document);
  }
}
