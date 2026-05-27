import { describe, expect, test, beforeEach, afterEach } from "vitest";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { StateStore } from "src/state/StateStore";
import type { StackDefinition } from "src/types/stack";

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

  test("list returns summary of all stacks", () => {
    store.write("a", makeDef("a"));
    store.write("b", makeDef("b"));
    const names = store
      .list()
      .map((s) => s.name)
      .sort();
    expect(names).toEqual(["a", "b"]);
  });

  test("remove archives by default", () => {
    store.write("doomed", makeDef("doomed"));
    store.remove("doomed");
    expect(store.read("doomed")).toBeNull();
    const archive = path.join(tmpRoot, "stacks", ".archive");
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
    const lines = fs
      .readFileSync(path.join(tmpRoot, "history.json"), "utf-8")
      .trim()
      .split("\n");
    expect(lines).toHaveLength(2);
    expect(JSON.parse(lines[0]!).action).toBe("apply");
  });

  test("summary produces redacted YAML for system prompt", () => {
    const def = makeDef("s");
    def.services.web!.environment = { NODE_ENV: "prod", API_KEY: "real" };
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
});
