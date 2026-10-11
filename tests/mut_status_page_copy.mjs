#!/usr/bin/env node
/** Apply one file mutation, run honesty tests in a subprocess, restore. */

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

const testFiles = [
  "tests/status_display.test.mjs",
  "tests/status_page_copy.test.mjs",
  "tests/status_page_behavior.test.mjs",
  "tests/status_page_app.test.mjs",
  "tests/status_page_render.test.mjs",
  "tests/brand_tokens_drift.test.mjs",
];

const mutations = [
  {
    name: "html_independent_checks",
    file: "index.html",
    old: "System status",
    new: "Hydracept status — Independent checks",
  },
  {
    name: "display_skip_stale_unknown",
    file: "status_display.mjs",
    old: 'if (stale) return "unknown"',
    new: 'if (false && stale) return "unknown"',
  },
  {
    name: "copy_stale_softens_uncertainty",
    file: "status_copy.mjs",
    old: "can't tell if things are healthy",
    new: "all systems nominal",
  },
  {
    name: "uptime_collecting_data_returns",
    file: "status_display.mjs",
    old: "if (row?.history_collecting) {\n    return null;\n  }",
    new: 'if (row?.history_collecting) {\n    return "100%";\n  }',
  },
  {
    name: "pill_overall_operational_shows_outage",
    file: "status_copy.mjs",
    old: 'if (status === "operational") return "All checks passing"',
    new: 'if (status === "operational") return "Outage"',
  },
  {
    name: "pill_component_down_shows_up",
    file: "status_copy.mjs",
    old: 'if (status === "down") return "Outage"',
    new: 'if (status === "down") return "Up"',
  },
  {
    name: "pill_degraded_shows_operational",
    file: "status_copy.mjs",
    old: 'if (status === "degraded") return "Degraded"',
    new: 'if (status === "degraded") return "All checks passing"',
  },
  {
    name: "missing_generated_at_not_stale",
    file: "status_display.mjs",
    old: "export function isProbeStale(doc, clientNowMs, responseDateMs) {\n  if (!doc?.generated_at) return true;",
    new: "export function isProbeStale(doc, clientNowMs, responseDateMs) {\n  if (!doc?.generated_at) return false;",
  },
  {
    name: "uptime_null_shows_100",
    file: "status_display.mjs",
    old: "if (row?.uptime_percent_90d == null) {\n    return null;\n  }",
    new: 'if (row?.uptime_percent_90d == null) {\n    return "100%";\n  }',
  },
  {
    name: "timestamp_skew_ignored_in_summary",
    file: "status_copy.mjs",
    old: "if (view.timestampSkewed) {",
    new: "if (false && view.timestampSkewed) {",
  },
  {
    name: "recovery_summary_disabled",
    file: "status_copy.mjs",
    old: "if (view.stateRecovered) {",
    new: "if (false && view.stateRecovered) {",
  },
  {
    name: "dom_forces_operational_pill",
    file: "status_page_dom.mjs",
    old: "pill.textContent = overallPillLabel(view.overall);",
    new: 'pill.textContent = overallPillLabel("operational");',
  },
  {
    name: "load_failure_hides_banner",
    file: "status_page_dom.mjs",
    old: "banner.hidden = false;",
    new: "banner.hidden = true;",
  },
  {
    name: "load_failure_exposes_raw_error",
    file: "status_page_dom.mjs",
    old: "meta.textContent = LOAD_FAILURE_MESSAGE;",
    new: 'meta.textContent = "SyntaxError: unexpected token in JSON";',
  },
  {
    name: "stale_shows_checked_not_last_result",
    file: "status_copy.mjs",
    old: "parts.push(`Last result: ${detail}`);",
    new: "parts.push(detail); parts.push(`Checked just now`);",
  },
  {
    name: "history_cells_stretch_full_width",
    file: "styles.css",
    old: "flex: 0 0 4px;",
    new: "flex: 1 1 2px;",
  },
  {
    name: "light_mode_reintroduced",
    file: "brand/tokens.css",
    old: "/* Derived from packages/brand/tokens.css plus status-pill tokens (dark theme only). */",
    new: "/* Derived from packages/brand/tokens.css plus status-pill tokens (dark theme only). */\n@media (prefers-color-scheme: light) { :root { color-scheme: light; } }",
  },
  {
    name: "dom_component_pill_always_up",
    file: "status_page_dom.mjs",
    old: "pill.textContent = componentPillLabel(shown);",
    new: 'pill.textContent = componentPillLabel("operational");',
  },
  {
    name: "dom_stale_row_shows_checked_line",
    file: "status_page_dom.mjs",
    old: "stale: view.stale || view.timestampSkewed,",
    new: "stale: false,",
  },
  {
    name: "component_line_shows_uptime_null",
    file: "status_copy.mjs",
    old: "if (uptimeLabel != null && uptimeLabel !== \"\") {",
    new: 'parts.push("90-day uptime null"); if (false && uptimeLabel != null && uptimeLabel !== "") {',
  },
  {
    name: "recovery_shows_raw_reason",
    file: "status_copy.mjs",
    old: "return `Our saved check history was unreadable, so we started it over. Older history may be missing. Last successful check was ${formatWhen(doc.generated_at)}.`;",
    new: "return `Recovered (${doc.state_recovery?.reason}). Last check ${formatWhen(doc.generated_at)}.`;",
  },
];

function runHonestyTests() {
  const proc = spawnSync(process.execPath, ["--test", ...testFiles], { cwd: root, encoding: "utf-8" });
  return proc.status === 0;
}

const survivors = [];
for (const mut of mutations) {
  const filePath = path.join(root, mut.file);
  const original = fs.readFileSync(filePath, "utf8");
  if (!original.includes(mut.old)) {
    console.error(`skip ${mut.name}: anchor missing`);
    continue;
  }
  fs.writeFileSync(filePath, original.replace(mut.old, mut.new, 1), "utf8");
  const ok = runHonestyTests();
  fs.writeFileSync(filePath, original, "utf8");
  if (ok) {
    survivors.push(mut.name);
  }
}

if (survivors.length) {
  console.error("mut_status_page_copy surviving mutations:", survivors.join(", "));
  process.exit(1);
}
console.log(`mut_status_page_copy: all ${mutations.length} mutations killed.`);
