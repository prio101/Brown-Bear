/**
 * Token conformance check (BB-102 §102.6).
 *
 * The token layer is only useful if bypassing it fails the build. This rejects a
 * raw color, a raw font-size, and an off-grid spacing value in component source.
 *
 * Three files are allowed to contain literals, because defining the tokens is
 * their entire job. Everything else references them.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(ROOT, "src");

/** Files whose job is to define literals. */
const COLOR_ALLOWED = new Set([
  "src/styles/theme.generated.css",
  "src/styles/chart-tokens.css",
  "src/styles/tokens.css",
]);
// type.css defines the scale; global.css sets the document base size, which is
// the one font-size that cannot itself come from a class.
const FONT_SIZE_ALLOWED = new Set(["src/styles/type.css", "src/styles/global.css"]);
const SPACING_ALLOWED = new Set(["src/styles/tokens.css", "src/styles/type.css"]);

/**
 * "On the grid" means a multiple of 4 (DESIGN-BOOK.md §4), not merely a member of
 * the spacing scale — widths and breakpoints are legitimately 120px or 600px.
 * 1–3px are hairlines and borders. Fractional values are tracking and are left
 * to the type scale.
 */
const isOnGrid = (value) =>
  !Number.isInteger(value) || value <= 3 || value % 4 === 0;

const RULES = [
  {
    name: "raw color",
    allowed: COLOR_ALLOWED,
    // Hex, rgb()/rgba(), hsl()/hsla() — anything that is not a var().
    pattern: /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/g,
    hint: "use a var(--bb-*) token",
  },
  {
    name: "raw font-size",
    allowed: FONT_SIZE_ALLOWED,
    // Capture the value and test it, rather than trying to exclude "var(" inside
    // the pattern: `\s*` backtracks, so a negative character class after it
    // happily matches the space and the declaration slips through.
    pattern: /font-size\s*:\s*([^;}]+)|fontSize\s*:\s*([^,}]+)/g,
    hint: "use a type-scale class, <Text role=…>, or a var(--bb-*) token",
    filter: (match) => {
      const value = (match[1] ?? match[2] ?? "").trim();
      return !value.startsWith("var(");
    },
  },
  {
    name: "off-grid length",
    allowed: SPACING_ALLOWED,
    // The decimal group matters: without it "0.5px" matches as "5px" and a
    // tracking value gets reported as an off-grid length.
    pattern: /(?<![\w.-])(\d+(?:\.\d+)?)px/g,
    hint: "use a var(--bb-space-*) token or a value on the 4px grid",
    filter: (match) => !isOnGrid(Number(match[1])),
  },
];

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.(css|ts|tsx)$/.test(entry)) out.push(full);
  }
  return out;
}

const failures = [];

for (const file of walk(SRC)) {
  const rel = relative(ROOT, file).split("\\").join("/");
  const lines = readFileSync(file, "utf8").split("\n");

  for (const rule of RULES) {
    if (rule.allowed.has(rel)) continue;
    lines.forEach((line, index) => {
      // Skip comment-only lines: a hex in a comment documents a decision.
      const trimmed = line.trim();
      if (trimmed.startsWith("*") || trimmed.startsWith("//") || trimmed.startsWith("/*")) return;

      for (const match of line.matchAll(rule.pattern)) {
        if (rule.filter && !rule.filter(match)) continue;
        failures.push({ rel, line: index + 1, rule: rule.name, text: trimmed, hint: rule.hint });
      }
    });
  }
}

if (failures.length === 0) {
  console.log("check-tokens: clean — no raw colors, font sizes or off-grid lengths");
  process.exit(0);
}

console.error(`check-tokens: ${failures.length} violation(s)\n`);
for (const f of failures) {
  console.error(`  ${f.rel}:${f.line}  [${f.rule}]  ${f.hint}`);
  console.error(`    ${f.text.slice(0, 100)}`);
}
process.exit(1);
