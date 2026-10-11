import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";

import {
  INCIDENTS_EMPTY,
  LOAD_FAILURE_MESSAGE,
  PAGE_TAGLINE,
  componentPillLabel,
  overallPillLabel,
  overallSummary,
} from "../status_copy.mjs";
import { formatUptimeLabel, pageViewModel } from "../status_display.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));

describe("status page copy", () => {
  it("avoids stiff marketing phrasing in static html", () => {
    const html = fs.readFileSync(path.join(here, "..", "index.html"), "utf8");
    assert.doesNotMatch(html, /Independent checks/i);
    assert.doesNotMatch(html, /Treat all components/i);
    assert.doesNotMatch(html, /collecting data/i);
    assert.match(html, /System status/);
    assert.match(html, /hydracept-mark\.png/);
    assert.doesNotMatch(html, /prefers-color-scheme:\s*light/i);
  });

  it("styles import brand tokens", () => {
    const css = fs.readFileSync(path.join(here, "..", "styles.css"), "utf8");
    assert.match(css, /@import "\.\/brand\/tokens\.css"/);
    assert.match(css, /--hydracept-accent/);
    assert.match(css, /width: fit-content/);
    assert.match(css, /flex: 0 0 4px/);
    assert.doesNotMatch(css, /flex: 1 1 2px/);
  });

  it("unknown pill label is calm not operational", () => {
    assert.equal(overallPillLabel("unknown"), "No recent data");
    assert.notEqual(componentPillLabel("unknown"), "Up");
  });

  it("stale summary explains uncertainty in plain language", () => {
    const doc = {
      generated_at: "2026-10-10T14:02:00.000Z",
      stale_after_seconds: 900,
      probe_interval_seconds: 300,
    };
    const view = pageViewModel(doc, Date.parse("2026-10-10T16:00:00.000Z"), Date.parse("2026-10-10T16:00:00.000Z"));
    assert.equal(view.stale, true);
    const text = overallSummary(view, doc, (iso) => iso || "never");
    assert.match(text, /can't tell if things are healthy/i);
    assert.doesNotMatch(text, /Treat all/i);
  });

  it("uptime hidden until history exists", () => {
    assert.equal(formatUptimeLabel({ history_collecting: true }), null);
    assert.equal(formatUptimeLabel({ uptime_percent_90d: 99.1 }), "99.1%");
  });

  it("incidents empty line is short", () => {
    assert.equal(INCIDENTS_EMPTY, "No incidents posted.");
    assert.ok(PAGE_TAGLINE.length < 220);
    assert.match(PAGE_TAGLINE, /We probe the public API/i);
    assert.ok(LOAD_FAILURE_MESSAGE.includes("couldn't load status data"));
  });
});
