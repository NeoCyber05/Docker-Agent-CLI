import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { QueryEngine } from "src/QueryEngine";
import type { ProviderEvent } from "src/services/api/types";
import { StateStore } from "src/state/StateStore";
import { afterEach, beforeEach, describe, expect, test } from "vitest";
import { MockComposeRunner } from "../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../tests/mocks/mockDockerEngine";

function fakeProvider(events: ProviderEvent[]) {
  return {
    name: "fake",
    stream: async function* () {
      for (const ev of events) yield ev;
    },
  };
}

describe("QueryEngine", () => {
  let tmp: string;
  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "qe-"));
  });
  afterEach(() => {
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  test("query is reusable across multiple turns", async () => {
    const engine = new QueryEngine({
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      cwd: tmp,
      provider: fakeProvider([
        { type: "text_delta", text: "first" },
        { type: "message_stop", stopReason: "end_turn" },
      ]),
    });

    const turn1: string[] = [];
    for await (const ev of engine.query("hi")) {
      if (ev.type === "assistant_text") turn1.push(ev.delta);
    }
    expect(turn1.join("")).toBe("first");

    engine.provider = fakeProvider([
      { type: "text_delta", text: "second" },
      { type: "message_stop", stopReason: "end_turn" },
    ]);

    const turn2: string[] = [];
    for await (const ev of engine.query("again")) {
      if (ev.type === "assistant_text") turn2.push(ev.delta);
    }
    expect(turn2.join("")).toBe("second");
  });

  test("respondTo resolves a pending permission request", async () => {
    const engine = new QueryEngine({
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      cwd: tmp,
      provider: fakeProvider([
        { type: "tool_use_start", id: "t1", name: "pull_image" },
        { type: "tool_use_delta", id: "t1", argsPartialJson: '{"image":"nginx"}' },
        { type: "tool_use_stop", id: "t1" },
        { type: "message_stop", stopReason: "tool_use" },
      ]),
    });

    const collected: string[] = [];
    const done = (async () => {
      for await (const ev of engine.query("pull nginx")) {
        if (ev.type === "permission_request") {
          engine.respondTo(ev.id, { kind: "approve" });
        }
        collected.push(ev.type);
      }
    })();
    await done;
    expect(collected).toContain("permission_request");
    expect(collected).toContain("tool_result");
  });

  test("respondTo returns false for unknown id", () => {
    const engine = new QueryEngine({
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      cwd: tmp,
      provider: fakeProvider([]),
    });
    expect(engine.respondTo("nonexistent", { kind: "approve" })).toBe(false);
  });

  test("reset clears messages and allow set", async () => {
    const engine = new QueryEngine({
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      cwd: tmp,
      provider: fakeProvider([
        { type: "text_delta", text: "hello" },
        { type: "message_stop", stopReason: "end_turn" },
      ]),
    });
    for await (const _ of engine.query("test")) {
      // drain
    }
    engine.reset();
    expect((engine as unknown as { messages: unknown[] }).messages).toHaveLength(0);
  });
});
