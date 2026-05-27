import { describe, expect, test } from "vitest";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { query } from "src/query";
import { StateStore } from "src/state/StateStore";
import { MockComposeRunner } from "../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../tests/mocks/mockDockerEngine";
import type { LoopContext } from "src/loopContext";
import type { PermissionResponse } from "src/types/permissions";
import type { ProviderEvent } from "src/services/api/types";

function fakeProvider(events: ProviderEvent[]) {
  return {
    name: "test-provider",
    stream: async function* () {
      for (const ev of events) yield ev;
    },
  };
}

async function collectEvents(
  userInput: string,
  events: ProviderEvent[],
  responses: PermissionResponse[],
) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "loop-"));
  const store = new StateStore(tmp);
  const responder = (() => {
    let i = 0;
    return () => Promise.resolve(responses[i++]) as Promise<PermissionResponse>;
  })();
  const ctx: LoopContext = {
    cwd: tmp,
    stateStore: store,
    dockerEngine: new MockDockerEngine() as never,
    composeRunner: new MockComposeRunner(tmp) as never,
    abortSignal: new AbortController().signal,
    requestPermission: responder,
    requestConfirm: responder,
    requestTypedConfirm: responder,
    requestSecretsInput: responder,
    allowSet: new Set(),
  };
  const collected = [];
  for await (const ev of query({
    messages: [{ role: "user", content: userInput }],
    ctx,
    provider: fakeProvider(events) as never,
  })) {
    collected.push(ev);
  }
  fs.rmSync(tmp, { recursive: true, force: true });
  return collected;
}

describe("query core loop", () => {
  test("plan-once: provider emits plan_stack tool_use → plan_ready → user approve → apply", async () => {
    const events = await collectEvents(
      "tạo nginx",
      [
        { type: "tool_use_start", id: "t1", name: "plan_stack" },
        {
          type: "tool_use_delta",
          id: "t1",
          argsPartialJson: JSON.stringify({
            stackName: "test",
            intent: "nginx",
            services: { web: { image: "nginx:1.27-alpine" } },
          }),
        },
        { type: "tool_use_stop", id: "t1" },
        { type: "message_stop", stopReason: "tool_use" },
      ],
      [{ kind: "approve" }],
    );
    expect(events.some((e) => e.type === "plan_ready")).toBe(true);
    expect(events.some((e) => e.type === "tool_result" && e.name === "apply_stack")).toBe(true);
  });

  test("react: provider emits text only → end_turn → loop exits", async () => {
    const events = await collectEvents(
      "what stacks do I have?",
      [
        { type: "text_delta", text: "You have no stacks." },
        { type: "message_stop", stopReason: "end_turn" },
      ],
      [],
    );
    const texts = events
      .filter((e): e is { type: "assistant_text"; delta: string } => e.type === "assistant_text")
      .map((e) => e.delta)
      .join("");
    expect(texts).toContain("You have no stacks");
  });
});