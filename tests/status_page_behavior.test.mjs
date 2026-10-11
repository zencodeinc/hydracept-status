import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  componentPillLabel,
  componentStatusLine,
  overallPillLabel,
  overallSummary,
} from "../status_copy.mjs";
import {
  formatUptimeLabel,
  formatUptimePercent,
  isProbeStale,
  isTimestampSkewed,
  pageViewModel,
  probeDataAgeSeconds,
} from "../status_display.mjs";

const formatWhen = (iso) => iso || "never";

describe("pill labels match every probe state", () => {
  it("overall labels", () => {
    assert.equal(overallPillLabel("operational"), "All checks passing");
    assert.equal(overallPillLabel("degraded"), "Some issues");
    assert.equal(overallPillLabel("down"), "Outage");
    assert.equal(overallPillLabel("unknown"), "No recent data");
  });

  it("component labels", () => {
    assert.equal(componentPillLabel("operational"), "Up");
    assert.equal(componentPillLabel("degraded"), "Degraded");
    assert.equal(componentPillLabel("down"), "Outage");
    assert.equal(componentPillLabel("unknown"), "No recent data");
  });
});

describe("staleness and skew", () => {
  it("missing generated_at is stale with null age", () => {
    const doc = { stale_after_seconds: 900 };
    const now = Date.parse("2026-10-10T12:00:00.000Z");
    assert.equal(isProbeStale(doc, now, now), true);
    assert.equal(isTimestampSkewed(doc, now, now), true);
    assert.equal(probeDataAgeSeconds(doc, now, now), null);
    const view = pageViewModel(doc, now, now);
    assert.equal(view.stale, true);
    assert.equal(view.timestampSkewed, true);
  });

  it("future generated_at uses skew copy not zero seconds", () => {
    const doc = {
      generated_at: "2026-10-10T14:00:00.000Z",
      stale_after_seconds: 900,
      overall: "operational",
      components: { api: { status: "operational", detail: "healthz ok" } },
    };
    const now = Date.parse("2026-10-10T12:00:00.000Z");
    const view = pageViewModel(doc, now, now);
    assert.equal(view.timestampSkewed, true);
    assert.equal(view.overall, "unknown");
    assert.equal(probeDataAgeSeconds(doc, now, now), null);
    const text = overallSummary(view, doc, formatWhen);
    assert.match(text, /timestamp on this report looks wrong/i);
    assert.doesNotMatch(text, /0 seconds/i);
    assert.doesNotMatch(text, /Last good check/i);
  });
});

describe("uptime display", () => {
  it("does not round 99.996% up to 100%", () => {
    assert.equal(formatUptimePercent(99.996), "99.9%");
    assert.equal(formatUptimeLabel({ uptime_percent_90d: 99.996 }), "99.9%");
  });

  it("returns null without history data", () => {
    assert.equal(formatUptimeLabel({}), null);
    assert.equal(formatUptimeLabel({ uptime_percent_90d: null }), null);
    assert.equal(formatUptimeLabel({ history_collecting: true, uptime_percent_90d: 100 }), null);
  });
});

describe("component copy when stale", () => {
  it("labels last result instead of implying a fresh check", () => {
    const line = componentStatusLine(
      { detail: "healthz ok", last_checked_at: "2026-10-09T12:00:00.000Z" },
      formatWhen,
      null,
      { stale: true },
    );
    assert.match(line, /Last result: healthz ok/);
    assert.doesNotMatch(line, /Checked /);
  });
});

describe("recovery summary", () => {
  it("does not expose raw state recovery reasons", () => {
    const doc = {
      generated_at: "2026-10-10T12:00:00.000Z",
      stale_after_seconds: 900,
      state_recovered: true,
      state_recovery: { reason: "invalid JSON" },
    };
    const view = pageViewModel(doc, Date.parse("2026-10-10T12:01:00.000Z"), Date.parse("2026-10-10T12:01:00.000Z"));
    assert.equal(view.stateRecovered, true);
    const text = overallSummary(view, doc, formatWhen);
    assert.match(text, /saved check history was unreadable/i);
    assert.match(text, /started it over/i);
    assert.doesNotMatch(text, /invalid JSON/i);
    assert.doesNotMatch(text, /platform reset/i);
  });
});
