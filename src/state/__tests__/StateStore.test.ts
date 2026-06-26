import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { STACK_STATES_DIR_NAME } from "src/config";
import { StateStore } from "src/state/StateStore";
import type { StackDefinition } from "src/types/stack";
import { afterEach, beforeEach, describe, expect, test } from "vitest";

function makeDef(name: string): StackDefinition {
  return {
    "x-docker-agent": {
      name,
      createdAt: "2026-05-26T00:00:00Z",
      lastApplied: null,
      intent: "test",
      provider: "gemini",
      generatedBy: "test",
      envFileSources: {},
    },
    services: { web: { image: "nginx:1.27-alpine" } },
  };
}

describe("StateStore", () => {
  let tmpRoot: string;
  let store: StateStore;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "docker-agent-test-"));
    store = new StateStore(tmpRoot);
  });

  afterEach(() => {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  test("write then read roundtrip", () => {
    const def = makeDef("webapp");
    store.write("webapp", def);
    expect(store.read("webapp")).toEqual(def);
  });

  test("read returns null when missing", () => {
    expect(store.read("missing")).toBeNull();
  });

  test("read throws a clear error for invalid stack YAML", () => {
    fs.writeFileSync(path.join(tmpRoot, STACK_STATES_DIR_NAME, "bad.yaml"), "services: {}\n");

    expect(() => store.read("bad")).toThrow(/Invalid stack state.*bad\.yaml/);
  });

  test("list returns summary of all stacks", () => {
    store.write("a", makeDef("a"));
    store.write("b", makeDef("b"));
    const names = store
      .list()
      .map((s) => s.name)
      .sort();
    expect(names).toEqual(["a", "b"]);
  });

  test("list skips malformed stack files", () => {
    const warnings: string[] = [];
    store = new StateStore(tmpRoot, { warn: (message) => warnings.push(message) });
    store.write("good", makeDef("good"));
    fs.writeFileSync(path.join(tmpRoot, STACK_STATES_DIR_NAME, "bad.yaml"), "not: a stack\n");

    expect(store.list()).toEqual([{ name: "good", serviceCount: 1, lastApplied: null }]);
    expect(warnings.join("\n")).toMatch(/Skipping invalid stack state.*bad\.yaml/);
  });

  test("remove archives by default", () => {
    store.write("doomed", makeDef("doomed"));
    store.remove("doomed");
    expect(store.read("doomed")).toBeNull();
    const archive = path.join(tmpRoot, "archive");
    expect(fs.readdirSync(archive)).toContain("doomed.yaml");
  });

  test("appendHistory writes JSONL", () => {
    store.appendHistory({
      ts: "2026-05-26T00:00:00Z",
      sessionId: "s",
      stackName: "x",
      action: "apply",
      details: {},
    });
    store.appendHistory({
      ts: "2026-05-26T00:00:01Z",
      sessionId: "s",
      stackName: "x",
      action: "drift_detected",
      details: {},
    });
    const lines = fs.readFileSync(path.join(tmpRoot, "history.json"), "utf-8").trim().split("\n");
    expect(lines).toHaveLength(2);
    const [firstLine] = lines;
    if (firstLine === undefined) throw new Error("missing first history line");
    expect(JSON.parse(firstLine).action).toBe("apply");
  });

  test("summary produces redacted YAML for system prompt", () => {
    const def = makeDef("s");
    const web = def.services.web;
    if (web === undefined) throw new Error("missing web service");
    web.environment = { NODE_ENV: "prod", API_KEY: "real" };
    store.write("s", def);
    const summary = store.summary();
    expect(summary).toContain("NODE_ENV: prod");
    expect(summary).not.toContain("real");
    expect(summary).toContain("***");
  });

  test("acquireLock prevents concurrent acquire", async () => {
    const release = await store.acquireLock("x");
    await expect(store.acquireLock("x", { timeoutMs: 50 })).rejects.toThrow(/lock/i);
    release();
    const release2 = await store.acquireLock("x");
    release2();
  });

  test("acquireLock removes stale lock files", async () => {
    fs.writeFileSync(path.join(tmpRoot, "locks", "stale.lock"), "99999999");

    const release = await store.acquireLock("stale", { timeoutMs: 0 });

    release();
  });

  test("migrates legacy stacks/ directory to states/", () => {
    const legacyRoot = fs.mkdtempSync(path.join(os.tmpdir(), "docker-agent-legacy-"));
    fs.mkdirSync(path.join(legacyRoot, "stacks"), { recursive: true });
    fs.writeFileSync(path.join(legacyRoot, "stacks", "legacy.yaml"), "services: {}\n");

    new StateStore(legacyRoot);

    expect(fs.existsSync(path.join(legacyRoot, "stacks"))).toBe(false);
    expect(fs.existsSync(path.join(legacyRoot, STACK_STATES_DIR_NAME, "legacy.yaml"))).toBe(true);
    fs.rmSync(legacyRoot, { recursive: true, force: true });
  });
});
