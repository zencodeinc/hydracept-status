import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";

const here = path.dirname(fileURLToPath(import.meta.url));

function normalizeBrandBase(css) {
  return css
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !line.startsWith("--status-"))
    .filter((line) => !line.includes("color-scheme"))
    .join("\n");
}

describe("brand tokens drift", () => {
  it("status tokens.css matches marketing base variables", () => {
    const pkg = fs.readFileSync(path.join(here, "..", "brand", "marketing-tokens-base.css"), "utf8");
    const status = fs.readFileSync(path.join(here, "..", "brand", "tokens.css"), "utf8");
    assert.equal(normalizeBrandBase(status), normalizeBrandBase(pkg));
    assert.doesNotMatch(status, /prefers-color-scheme:\s*light/);
  });
});
