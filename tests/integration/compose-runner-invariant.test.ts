import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, test } from "vitest";

function* walk(dir: string): Generator<string> {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "node_modules" || e.name === "dist" || e.name === "coverage") continue;
      yield* walk(p);
    } else if (e.isFile() && (e.name.endsWith(".ts") || e.name.endsWith(".tsx"))) {
      yield p;
    }
  }
}

describe("ComposeRunner invariant", () => {
  test("no source file outside composeRunner.ts contains a raw `docker compose` invocation", () => {
    const root = path.resolve(__dirname, "../../src");
    const offenders: string[] = [];
    for (const file of walk(root)) {
      if (file.endsWith(path.join("services", "docker", "composeRunner.ts"))) continue;
      const text = fs.readFileSync(file, "utf-8");
      // We allow the string in markdown/docstrings; the regex looks for it as an executable token.
      if (/\bspawn\([^)]*docker[^)]*compose/.test(text)) offenders.push(file);
      if (/\bexec(?:Sync)?\([^)]*docker compose/.test(text)) offenders.push(file);
    }
    expect(offenders).toEqual([]);
  });
});
