import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import { parseHTML } from "linkedom";

import { formatUptimeLabel, pageViewModel } from "../status_display.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixtures = path.join(here, "fixtures");

function loadFixture(name) {
  return JSON.parse(fs.readFileSync(path.join(fixtures, name), "utf8"));
}

function renderPills(view) {
  const pills = [];
  pills.push({ id: "overall", status: view.overall });
  for (const [key, row] of Object.entries(view.components)) {
    pills.push({ id: key, status: row.displayed_status });
  }
  return pills;
}

describe("status page render against fixtures", () => {
  it("down fixture never renders operational pills", () => {
    const doc = loadFixture("status-down.json");
    const view = pageViewModel(doc, Date.parse("2026-10-09T12:05:00.000Z"), Date.parse("2026-10-09T12:05:00.000Z"));
    for (const pill of renderPills(view)) {
      assert.notEqual(pill.status, "operational", pill.id);
    }
  });

  it("stale fixture renders unknown", () => {
    const doc = loadFixture("status-stale.json");
    const view = pageViewModel(doc, Date.parse("2026-10-09T15:00:00.000Z"), Date.parse("2026-10-09T15:00:00.000Z"));
    assert.equal(view.overall, "unknown");
    assert.equal(view.components.api.displayed_status, "unknown");
  });

  it("degraded fixture keeps degraded", () => {
    const doc = loadFixture("status-degraded.json");
    const view = pageViewModel(doc, Date.parse("2026-10-09T12:02:00.000Z"), Date.parse("2026-10-09T12:02:00.000Z"));
    assert.equal(view.overall, "degraded");
  });

  it("index.html loads without third-party scripts", () => {
    const html = fs.readFileSync(path.join(here, "..", "index.html"), "utf8");
    const { document } = parseHTML(html);
    const scripts = [...document.querySelectorAll("script[src]")];
    assert.equal(scripts.length, 1);
    assert.match(scripts[0].getAttribute("src") || "", /^\.\//);
  });

  it("uptime label absent while history collects", () => {
    assert.equal(formatUptimeLabel({ history_collecting: true }), null);
  });

  it("index references only local script", () => {
    const html = fs.readFileSync(path.join(here, "..", "index.html"), "utf8");
    const { document } = parseHTML(html);
    for (const script of document.querySelectorAll("script[src]")) {
      const src = script.getAttribute("src") || "";
      assert.ok(!src.includes("google"), src);
    }
  });
});
