import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  displayComponentStatus,
  isProbeStale,
  pageViewModel,
  referenceNowMs,
} from "../status_display.mjs";

describe("displayComponentStatus", () => {
  it("never shows operational when stale", () => {
    assert.equal(displayComponentStatus("operational", true), "unknown");
    assert.equal(displayComponentStatus("down", true), "unknown");
  });

  it("does not upgrade degraded or down", () => {
    assert.equal(displayComponentStatus("degraded", false), "degraded");
    assert.equal(displayComponentStatus("down", false), "down");
  });

  it("mutation: forced operational return would fail", () => {
    const mutated = () => "operational";
    assert.notEqual(mutated("down", false), displayComponentStatus("down", false));
  });
});

describe("isProbeStale", () => {
  const doc = {
    generated_at: "2026-10-09T12:00:00.000Z",
    stale_after_seconds: 900,
  };

  it("uses HTTP Date header, not probe timestamps", () => {
    const responseDateMs = Date.parse("2026-10-09T12:20:00.000Z");
    assert.equal(isProbeStale(doc, Date.parse("2026-10-09T11:00:00.000Z"), responseDateMs), true);
  });

  it("ignores legacy server_time equal to generated_at", () => {
    const legacy = {
      ...doc,
      server_time: doc.generated_at,
    };
    const responseDateMs = Date.parse("2026-10-09T15:00:00.000Z");
    assert.equal(isProbeStale(legacy, Date.parse("2026-10-09T12:01:00.000Z"), responseDateMs), true);
  });

  it("treats future generated_at as stale", () => {
    const skewed = {
      generated_at: "2026-10-09T13:00:00.000Z",
      stale_after_seconds: 900,
    };
    assert.equal(
      isProbeStale(skewed, Date.parse("2026-10-09T12:00:00.000Z"), Date.parse("2026-10-09T12:00:00.000Z")),
      true,
    );
  });

  it("missing generated_at is always stale", () => {
    assert.equal(isProbeStale({ stale_after_seconds: 900 }, Date.now(), Date.now()), true);
  });

  it("mutation: ignoring stale check would fail", () => {
    const responseDateMs = Date.parse("2026-10-09T12:20:00.000Z");
    const alwaysFresh = () => false;
    assert.equal(alwaysFresh(doc, 0, responseDateMs), false);
    assert.equal(isProbeStale(doc, 0, responseDateMs), true);
  });
});

describe("pageViewModel", () => {
  it("maps down document without upgrading", () => {
    const doc = {
      overall: "down",
      generated_at: "2026-10-09T12:00:00.000Z",
      stale_after_seconds: 900,
      components: {
        api: { status: "down", display_name: "API" },
      },
    };
    const view = pageViewModel(doc, Date.now(), Date.parse("2026-10-09T12:01:00.000Z"));
    assert.equal(view.overall, "down");
    assert.equal(view.components.api.displayed_status, "down");
    assert.equal(view.clockSource, "http-date");
  });

  it("flags client clock fallback when Date header missing", () => {
    const doc = {
      overall: "operational",
      generated_at: "2026-10-09T12:00:00.000Z",
      stale_after_seconds: 900,
      components: { api: { status: "operational" } },
    };
    const view = pageViewModel(doc, Date.parse("2026-10-09T12:01:00.000Z"), null);
    assert.equal(view.clockSource, "client-fallback");
  });
});

describe("referenceNowMs", () => {
  it("prefers response Date over client", () => {
    const { referenceMs, clockSource } = referenceNowMs(1, 2);
    assert.equal(referenceMs, 2);
    assert.equal(clockSource, "http-date");
  });
});
