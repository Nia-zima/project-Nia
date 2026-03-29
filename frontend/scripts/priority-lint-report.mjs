import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

const UPDATE_BASELINE = process.argv.includes("--update-baseline");
const ROOT = process.cwd();
const REPORT_PATH = path.join(ROOT, ".lint-priority.json");
const BASELINE_PATH = path.join(ROOT, "lint-priority-baseline.json");
const TARGET_GLOBS = ["app/**/*.{ts,tsx}", "components/**/*.{ts,tsx}", "lib/**/*.{ts,tsx}"];

const PRIORITY_RULES = new Set(["@typescript-eslint/no-explicit-any"]);
const REACT_HOOK_PREFIX = "react-hooks/";

function loadJson(filePath) {
  if (!fs.existsSync(filePath)) return null;
  const raw = fs.readFileSync(filePath, "utf8");
  return JSON.parse(raw);
}

function runEslint() {
  const args = ["eslint", ...TARGET_GLOBS, "-f", "json", "-o", ".lint-priority.json"];
  const npxCmd = process.platform === "win32" ? "npx.cmd" : "npx";
  const result = spawnSync(npxCmd, args, {
    cwd: ROOT,
    stdio: "inherit",
  });
  // We intentionally ignore non-zero exit; report is still useful for baseline/ratchet.
  return result.status ?? 0;
}

function collectCounts(eslintJson) {
  const byRule = {};
  let total = 0;
  for (const file of eslintJson || []) {
    for (const msg of file.messages || []) {
      const ruleId = msg.ruleId || "";
      if (!ruleId) continue;
      if (PRIORITY_RULES.has(ruleId) || ruleId.startsWith(REACT_HOOK_PREFIX)) {
        byRule[ruleId] = (byRule[ruleId] || 0) + 1;
        total += 1;
      }
    }
  }
  return { total, by_rule: byRule };
}

function sortedObject(obj) {
  return Object.fromEntries(Object.entries(obj).sort((a, b) => a[0].localeCompare(b[0])));
}

runEslint();
const report = loadJson(REPORT_PATH);
if (!report) {
  console.error("[priority-lint] missing report file:", REPORT_PATH);
  process.exit(2);
}

const current = collectCounts(report);
current.by_rule = sortedObject(current.by_rule);

if (UPDATE_BASELINE) {
  const payload = {
    updated_at: new Date().toISOString(),
    total: current.total,
    by_rule: current.by_rule,
  };
  fs.writeFileSync(BASELINE_PATH, JSON.stringify(payload, null, 2), "utf8");
  console.log("[priority-lint] baseline updated:", BASELINE_PATH);
  console.log("[priority-lint] total =", current.total);
  process.exit(0);
}

const baseline = loadJson(BASELINE_PATH);
if (!baseline) {
  console.error("[priority-lint] baseline not found. Run: npm run lint:priority:update");
  process.exit(2);
}

let hasRegression = false;
const allRuleIds = new Set([...Object.keys(current.by_rule), ...Object.keys(baseline.by_rule || {})]);
for (const ruleId of Array.from(allRuleIds).sort()) {
  const now = Number(current.by_rule[ruleId] || 0);
  const base = Number((baseline.by_rule || {})[ruleId] || 0);
  if (now > base) {
    hasRegression = true;
    console.error(`[priority-lint] regression: ${ruleId} ${base} -> ${now}`);
  }
}
if (Number(current.total) > Number(baseline.total || 0)) {
  hasRegression = true;
  console.error(`[priority-lint] total regression: ${(baseline.total || 0)} -> ${current.total}`);
}

console.log("[priority-lint] current total:", current.total);
console.log("[priority-lint] baseline total:", baseline.total || 0);
if (hasRegression) {
  process.exit(1);
}
console.log("[priority-lint] OK (no regression)");
