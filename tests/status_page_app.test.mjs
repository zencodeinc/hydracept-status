import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import { parseHTML } from "linkedom";

import { LOAD_FAILURE_MESSAGE, NOSCRIPT_MESSAGE, SHELL_WITHOUT_JS_MESSAGE } from "../status_copy.mjs";
import { bootstrapStatusPage } from "../status_page_dom.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixtures = path.join(here, "fixtures");

function loadShell() {
  const html = fs.readFileSync(path.join(here, "..", "index.html"), "utf8");
  return parseHTML(html);
}

function jsonResponse(body, dateHeader) {
  return {
    ok: true,
    status: 200,
    headers: {
      get(name) {
        if (name.toLowerCase() === "date") return dateHeader || "Thu, 09 Oct 2026 12:05:00 GMT";
        return null;
      },
    },
    json: async () => body,
  };
}

function componentRow(document, key) {
  const card = document.querySelector(`.component[data-component="${key}"]`);
  assert.ok(card, `missing component ${key}`);
  const pill = card.querySelector(".pill");
  const detail = card.querySelector(".component-detail");
  return {
    pillText: pill?.textContent ?? "",
    pillStatus: pill?.dataset?.status ?? "",
    detailText: detail?.textContent ?? "",
  };
}

async function renderStatus(document, statusDoc, nowMs) {
  const dateHeader = new Date(nowMs).toUTCString();
  await bootstrapStatusPage(
    document,
    async (url) =>
      url.includes("status.json") ? jsonResponse(statusDoc, dateHeader) : jsonResponse({ incidents: [] }, dateHeader),
    nowMs,
  );
}

describe("bootstrapStatusPage", () => {
  it("renders degraded fixture with correct overall and row pills", async () => {
    const statusDoc = JSON.parse(fs.readFileSync(path.join(fixtures, "status-degraded.json"), "utf8"));
    statusDoc.components.site.last_checked_at = "2026-10-09T12:00:00.000Z";
    const { window } = loadShell();
    const { document } = window;
    await renderStatus(document, statusDoc, Date.parse("2026-10-09T12:02:00.000Z"));
    const overall = document.getElementById("overall-pill");
    assert.equal(overall.dataset.status, "degraded");
    assert.equal(overall.textContent, "Some issues");
    const row = componentRow(document, "site");
    assert.equal(row.pillStatus, "degraded");
    assert.equal(row.pillText, "Degraded");
    assert.match(row.detailText, /wrong html/);
    assert.match(row.detailText, /Checked .+\./);
    assert.doesNotMatch(row.detailText, /Last result:/);
    assert.doesNotMatch(row.detailText, /90-day uptime null/i);
  });

  it("renders down fixture with outage row text and pill", async () => {
    const statusDoc = JSON.parse(fs.readFileSync(path.join(fixtures, "status-down.json"), "utf8"));
    statusDoc.components.api.last_checked_at = "2026-10-09T12:00:00.000Z";
    const { window } = loadShell();
    const { document } = window;
    await renderStatus(document, statusDoc, Date.parse("2026-10-09T12:05:00.000Z"));
    assert.equal(document.getElementById("overall-pill").textContent, "Outage");
    const row = componentRow(document, "api");
    assert.equal(row.pillText, "Outage");
    assert.equal(row.pillStatus, "down");
    assert.match(row.detailText, /^outage\. Checked .+\.$/);
  });

  it("renders stale rows with last result and no checked line", async () => {
    const statusDoc = JSON.parse(fs.readFileSync(path.join(fixtures, "status-stale.json"), "utf8"));
    statusDoc.components.api.detail = "healthz ok";
    statusDoc.components.api.last_checked_at = "2026-10-09T10:00:00.000Z";
    const { window } = loadShell();
    const { document } = window;
    await renderStatus(document, statusDoc, Date.parse("2026-10-09T15:00:00.000Z"));
    const row = componentRow(document, "api");
    assert.equal(row.pillText, "No recent data");
    assert.equal(row.pillStatus, "unknown");
    assert.equal(row.detailText, "Last result: healthz ok.");
    assert.doesNotMatch(row.detailText, /Checked /);
    assert.doesNotMatch(row.detailText, /healthz ok\. Checked/);
  });

  it("omits 90-day uptime line when history is not ready", async () => {
    const statusDoc = {
      overall: "operational",
      generated_at: "2026-10-10T12:00:00.000Z",
      stale_after_seconds: 900,
      components: {
        api: {
          status: "operational",
          display_name: "API",
          detail: "ok",
          last_checked_at: "2026-10-10T12:00:00.000Z",
          uptime_percent_90d: null,
          history_collecting: true,
        },
      },
    };
    const { window } = loadShell();
    const { document } = window;
    await renderStatus(document, statusDoc, Date.parse("2026-10-10T12:01:00.000Z"));
    const row = componentRow(document, "api");
    assert.equal(row.pillText, "Up");
    assert.match(row.detailText, /^ok\. Checked .+\.$/);
    assert.doesNotMatch(row.detailText, /90-day uptime/i);
    assert.doesNotMatch(row.detailText, /null/i);
  });

  it("shows load failure copy on fetch error without raw errors", async () => {
    const { window } = loadShell();
    const { document } = window;
    const fetchImpl = async () => {
      throw new Error("Secret internal parse failure XYZZY");
    };
    await bootstrapStatusPage(document, fetchImpl, Date.now());
    assert.equal(document.getElementById("overall-meta").textContent, LOAD_FAILURE_MESSAGE);
    assert.equal(document.getElementById("error-banner").textContent, LOAD_FAILURE_MESSAGE);
    assert.doesNotMatch(document.getElementById("error-banner").textContent, /XYZZY/);
    assert.equal(document.getElementById("overall-pill").dataset.status, "unknown");
    assert.equal(document.getElementById("error-banner").hidden, false);
  });

  it("shows load failure on malformed JSON", async () => {
    const { window } = loadShell();
    const { document } = window;
    const fetchImpl = async (url) => {
      if (url.includes("status.json")) {
        return {
          ok: true,
          status: 200,
          headers: { get: () => null },
          json: async () => {
            throw new SyntaxError("Unexpected token in JSON");
          },
        };
      }
      return jsonResponse({ incidents: [] });
    };
    await bootstrapStatusPage(document, fetchImpl, Date.now());
    assert.equal(document.getElementById("overall-meta").textContent, LOAD_FAILURE_MESSAGE);
    assert.doesNotMatch(document.getElementById("overall-meta").textContent, /Unexpected token/);
  });

  it("history bar width reflects day count not 90-day stretch", async () => {
    const statusDoc = {
      overall: "operational",
      generated_at: "2026-10-10T12:00:00.000Z",
      stale_after_seconds: 900,
      components: {
        api: {
          status: "operational",
          display_name: "API",
          detail: "ok",
          last_checked_at: "2026-10-10T12:00:00.000Z",
          history_days: [{ date: "2026-10-10", uptime_ratio: 1 }],
        },
      },
    };
    const { window } = loadShell();
    const { document } = window;
    await renderStatus(document, statusDoc, Date.parse("2026-10-10T12:01:00.000Z"));
    const cells = document.querySelectorAll(".history span");
    assert.equal(cells.length, 1);
    const label = document.querySelector(".history-label");
    assert.ok(label);
    assert.match(label.textContent, /Since Oct 10/i);
  });
});

describe("index.html shell", () => {
  it("includes noscript guidance and apple touch icon", () => {
    const html = fs.readFileSync(path.join(here, "..", "index.html"), "utf8");
    assert.match(html, /apple-touch-icon/);
    assert.match(html, /noscript/);
    assert.match(html, /hydracept\.com/);
    assert.match(html, /docs\.hydracept\.com/);
    assert.doesNotMatch(html, /Loading…/);
    assert.ok(NOSCRIPT_MESSAGE.includes("JavaScript"));
    assert.ok(SHELL_WITHOUT_JS_MESSAGE.includes("JavaScript"));
  });
});
