import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, test } from "vitest";

const ROOT = join(import.meta.dirname ?? __dirname, "..", "..");
const SRC = join(ROOT, "src");

function walk(dir: string): string[] {
  const results: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      results.push(...walk(full));
    } else if (full.endsWith(".ts") || full.endsWith(".tsx")) {
      results.push(full);
    }
  }
  return results;
}

describe("ComposeRunner invariant", () => {
  test("no source file outside composeRunner.ts spawns docker compose directly", () => {
    const files = walk(SRC);
    const offenders = files
      .filter((f) => !f.endsWith("composeRunner.ts") && !f.endsWith("composeRunner.test.ts"))
      .filter((f) => {
        const content = readFileSync(f, "utf-8");
        return /\bdocker[\s-]+compose\b/.test(content);
      })
      .map((f) => relative(ROOT, f));
    expect(offenders).toEqual([]);
  });
});

describe("Layer isolation invariant", () => {
  const L4_RESTRICTED = [
    join(SRC, "state", "rollback.ts"),
    join(SRC, "tools", "remediateDrift.ts"),
  ];

  const FORBIDDEN_PATTERNS = [
    /requestPermission/,
    /requestConfirm/,
    /requestTypedConfirm/,
    /requestSecretsInput/,
  ];

  test("L4 rollback helper does not reference user-interaction functions", () => {
    for (const file of L4_RESTRICTED) {
      const content = readFileSync(file, "utf-8");
      for (const pattern of FORBIDDEN_PATTERNS) {
        expect(
          pattern.test(content),
          `${relative(ROOT, file)} must not reference ${pattern.source}`,
        ).toBe(false);
      }
    }
  });
});
