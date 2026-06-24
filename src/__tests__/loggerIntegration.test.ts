import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, test } from "vitest";
import { MockComposeRunner } from "../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../tests/mocks/mockDockerEngine";
import { QueryEngine, type QueryEngineDeps } from "../QueryEngine";
import type { ProviderEvent } from "../services/api/types";
import { StateStore } from "../state/StateStore";
import { StructuredLogger } from "../state/logger";

function fakeProvider(events: ProviderEvent[]) {
  return {
    name: "test-provider",
    stream: async function* () {
      for (const ev of events) yield ev;
    },
  };
}

function multiCallProvider(eventLists: ProviderEvent[][]) {
  let callIdx = 0;
  return {
    name: "test-provider",
    stream: async function* () {
      const events = eventLists[callIdx] ?? [];
      callIdx++;
      for (const ev of events) yield ev;
    },
  };
}

describe("QueryEngine structured logging", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "qe-log-"));
    fs.writeFileSync(path.join(tmpDir, "project-policies.yaml"), "project: {}");
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  test("writes trace entries to <sessionId>.ndjson during a turn", async () => {
    const logDir = path.join(tmpDir, ".docker-agent", "logs");
    const sessionId = "trace-test-1";
    const logger = new StructuredLogger(logDir, sessionId);

    const deps: QueryEngineDeps = {
      cwd: tmpDir,
      stateStore: new StateStore(path.join(tmpDir, ".docker-agent")),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmpDir) as never,
      provider: fakeProvider([
        { type: "text_delta", text: "done" },
        { type: "message_stop", stopReason: "end_turn" },
      ]),
    };

    const engine = new QueryEngine(deps);
    engine.setLogger(logger);

    for await (const _ev of engine.query("hello")) {
      // drain
    }
    logger.close();

    const logPath = path.join(logDir, `${sessionId}.ndjson`);
    expect(fs.existsSync(logPath)).toBe(true);
    const content = fs.readFileSync(logPath, "utf-8");
    const entries = content
      .trim()
      .split("\n")
      .map((l) => JSON.parse(l));
    expect(entries.length).toBeGreaterThan(0);
    expect(entries.some((e) => e.category === "turn_start")).toBe(true);
    expect(entries.some((e) => e.category === "turn_end")).toBe(true);
  });

  test("emits iteration_summary with thought/action/observation structure", async () => {
    const logDir = path.join(tmpDir, ".docker-agent", "logs");
    const sessionId = "trace-test-2";
    const logger = new StructuredLogger(logDir, sessionId);

    const provider = multiCallProvider([
      [
        { type: "text_delta", text: "I will list stacks" },
        { type: "tool_use_start", id: "t1", name: "list_stacks" },
        { type: "tool_use_delta", id: "t1", argsPartialJson: "{}" },
        { type: "tool_use_stop", id: "t1" },
        { type: "message_stop", stopReason: "tool_use" },
      ],
      [
        { type: "text_delta", text: "No stacks." },
        { type: "message_stop", stopReason: "end_turn" },
      ],
    ]);

    const deps: QueryEngineDeps = {
      cwd: tmpDir,
      stateStore: new StateStore(path.join(tmpDir, ".docker-agent")),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmpDir) as never,
      provider,
    };

    const engine = new QueryEngine(deps);
    engine.setLogger(logger);
    for await (const _ev of engine.query("list my stacks")) {
      // drain
    }
    logger.close();

    const logPath = path.join(logDir, `${sessionId}.ndjson`);
    const entries = fs
      .readFileSync(logPath, "utf-8")
      .trim()
      .split("\n")
      .map((l) => JSON.parse(l));
    const summaries = entries.filter((e) => e.category === "iteration_summary");
    expect(summaries.length).toBeGreaterThanOrEqual(1);
    const summary = summaries[0];
    expect(summary.data).toHaveProperty("actions");
    expect(summary.data).toHaveProperty("observations");
    expect(summary.data.actions).toContain("list_stacks");
  });
});
