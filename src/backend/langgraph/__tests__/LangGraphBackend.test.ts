import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { LoopContext } from "src/loopContext";
import type { Provider, ProviderEvent } from "src/services/api/types";
import type { ComposeRunner } from "src/services/docker/composeRunner";
import type { EngineClient } from "src/services/docker/engineClient";
import { StateStore } from "src/state/StateStore";
import type { LoopEvent } from "src/types/events";
import { afterEach, beforeEach, describe, expect, test } from "vitest";
import { MockComposeRunner } from "../../../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../../../tests/mocks/mockDockerEngine";
import { LangGraphBackend } from "../LangGraphBackend";

function fakeProvider(calls: ProviderEvent[][]) {
  let callIdx = 0;
  return {
    name: "fake",
    stream: async function* () {
      const events = calls[callIdx++] ?? [];
      for (const ev of events) yield ev;
    },
  };
}

describe("LangGraphBackend smoke", () => {
  let tmp: string;
  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "lgb-"));
    fs.writeFileSync(path.join(tmp, "project-policies.yaml"), "project: {}");
  });
  afterEach(() => fs.rmSync(tmp, { recursive: true, force: true }));

  test("streams iteration_start, tool_call, tool_result and assistant_text", async () => {
    const ctx = {
      cwd: tmp,
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as unknown as EngineClient,
      composeRunner: new MockComposeRunner(tmp) as unknown as ComposeRunner,
      abortSignal: new AbortController().signal,
      requestPermission: async () => ({ kind: "approve" as const }),
      requestConfirm: async () => ({ kind: "approve" as const }),
      requestTypedConfirm: async () => ({ kind: "typed_confirm_value" as const, value: "x" }),
      requestSecretsInput: async () => ({ kind: "deny" as const }),
      allowSet: new Set<string>(),
    };
    const events: LoopEvent[] = [];
    const backend = new LangGraphBackend();
    for await (const ev of backend.query({
      messages: [{ role: "user", content: "list stacks" }],
      ctx: ctx as unknown as LoopContext,
      provider: fakeProvider([
        [
          { type: "tool_use_start", id: "t1", name: "list_stacks" },
          { type: "tool_use_delta", id: "t1", argsPartialJson: "{}" },
          { type: "tool_use_stop", id: "t1" },
          { type: "message_stop", stopReason: "tool_use" },
        ],
        [
          { type: "text_delta", text: "done" },
          { type: "message_stop", stopReason: "end_turn" },
        ],
      ]) as unknown as Provider,
    })) {
      events.push(ev);
    }
    const types = events.map((e) => e.type);
    expect(types).toContain("iteration_start");
    expect(types).toContain("tool_call");
    expect(types).toContain("tool_result");
    expect(types).toContain("assistant_text");
  });
});
