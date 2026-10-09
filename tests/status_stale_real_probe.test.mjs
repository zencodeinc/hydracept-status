import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";

import { pageViewModel } from "../status_display.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.join(here, "..");

function repoRootFromPublic() {
  if (fs.existsSync(path.join(publicDir, "scripts", "status_probe.py"))) {
    return publicDir;
  }
  return path.resolve(publicDir, "..", "..", "..");
}

function runRealProbe(statePath) {
  const root = repoRootFromPublic();
  const probe = path.join(root, "scripts", "status_probe.py");
  const bootstrap = fs.existsSync(path.join(root, "bootstrap", "probe-state.json"))
    ? path.join(root, "bootstrap", "probe-state.json")
    : path.join(publicDir, "status.json");
  fs.copyFileSync(bootstrap, statePath);
  const proc = spawnSync(
    process.env.PYTHON || "python3",
    [probe, "--state", statePath, "--write", statePath, "--mock-scenario", "ok"],
    { cwd: root, encoding: "utf-8", env: { ...process.env, HYDRACEPT_DEPLOY_SMOKE_API_KEY: "" } },
  );
  assert.equal(proc.status, 0, proc.stderr || proc.stdout);
  return JSON.parse(fs.readFileSync(statePath, "utf8"));
}

describe("real probe document staleness", () => {
  it("operational when fresh, unknown after 2h and 3d (HTTP Date clock)", () => {
    const statePath = path.join(os.tmpdir(), `probe-state-${process.pid}.json`);
    try {
      const doc = runRealProbe(statePath);
      assert.equal("server_time" in doc, false, "probe must not write server_time as now");
      const generatedMs = Date.parse(doc.generated_at);
      assert.ok(Number.isFinite(generatedMs));

      const fresh = pageViewModel(doc, generatedMs + 60_000, generatedMs + 60_000);
      assert.equal(fresh.stale, false);
      assert.equal(fresh.overall, "operational");

      const twoHours = pageViewModel(doc, generatedMs + 7_200_000, generatedMs + 7_200_000);
      assert.equal(twoHours.stale, true);
      assert.equal(twoHours.overall, "unknown");

      const threeDays = pageViewModel(doc, generatedMs + 259_200_000, generatedMs + 259_200_000);
      assert.equal(threeDays.stale, true);
      assert.equal(threeDays.overall, "unknown");
    } finally {
      fs.rmSync(statePath, { force: true });
    }
  });
});
