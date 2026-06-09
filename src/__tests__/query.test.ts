import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { LoopContext } from "src/loopContext";
import { query } from "src/query";
import type { ProviderEvent } from "src/services/api/types";
import { StateStore } from "src/state/StateStore";
import type { PermissionResponse } from "src/types/permissions";
import { describe, expect, test } from "vitest";
import { MockComposeRunner } from "../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../tests/mocks/mockDockerEngine";

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

function fakeProvider(events: ProviderEvent[]) {
  return multiCallProvider([events]);
}

async function collectEvents(
  userInput: string,
  providerParam: { events?: ProviderEvent[]; perCall?: ProviderEvent[][] },
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
    healthCheckDeadlineMs: 0, // avoid health-gate polling in unit tests
    requestPermission: responder,
    requestConfirm: responder,
    requestTypedConfirm: responder,
    requestSecretsInput: responder,
    allowSet: new Set(),
  };

  const provider = providerParam.perCall
    ? multiCallProvider(providerParam.perCall)
    : fakeProvider(providerParam.events as ProviderEvent[]);

  const collected = [];
  for await (const ev of query({
    messages: [{ role: "user", content: userInput }],
    ctx,
    provider: provider as never,
  })) {
    collected.push(ev);
  }
  fs.rmSync(tmp, { recursive: true, force: true });
  return collected;
}

function makePlanStackToolEvents(id: string, input: object): ProviderEvent[] {
  return [
    { type: "tool_use_start", id, name: "plan_stack" },
    { type: "tool_use_delta", id, argsPartialJson: JSON.stringify(input) },
    { type: "tool_use_stop", id },
    { type: "message_stop", stopReason: "tool_use" as const },
  ];
}

describe("query core loop", () => {
  test("plan-once: provider emits plan_stack tool_use → tool_result for plan_stack + apply_stack on approve", async () => {
    const events = await collectEvents(
      "tạo nginx",
      {
        events: makePlanStackToolEvents("t1", {
          stackName: "test",
          intent: "nginx",
          services: { web: { image: "nginx:1.27-alpine" } },
        }),
      },
      [{ kind: "approve" }],
    );
    expect(events.some((e) => e.type === "tool_result" && e.name === "plan_stack")).toBe(true);
    expect(events.some((e) => e.type === "tool_result" && e.name === "apply_stack")).toBe(true);
  });

  test("plan-once: user declines plan → no apply_stack tool_result", async () => {
    const events = await collectEvents(
      "create app",
      {
        events: makePlanStackToolEvents("t1", {
          stackName: "test",
          intent: "app",
          services: { web: { image: "nginx:1.27-alpine" } },
        }),
      },
      [{ kind: "deny" }],
    );
    expect(events.some((e) => e.type === "tool_result" && e.name === "plan_stack")).toBe(true);
    expect(events.some((e) => e.type === "tool_result" && e.name === "apply_stack")).toBe(false);
  });

  test("react: provider emits text only → end_turn → loop exits", async () => {
    const events = await collectEvents(
      "what stacks do I have?",
      {
        events: [
          { type: "text_delta", text: "You have no stacks." },
          { type: "message_stop", stopReason: "end_turn" as const },
        ],
      },
      [],
    );
    const texts = events
      .filter((e): e is { type: "assistant_text"; delta: string } => e.type === "assistant_text")
      .map((e) => e.delta)
      .join("");
    expect(texts).toContain("You have no stacks");
    expect(events.some((e) => e.type === "iteration_start")).toBe(true);
  });

  test("react: destroy_all typed confirm mismatch → no tool_result for destroy", async () => {
    const destroyToolEvents: ProviderEvent[] = [
      { type: "tool_use_start", id: "t1", name: "destroy_all_stacks" },
      {
        type: "tool_use_delta",
        id: "t1",
        argsPartialJson: JSON.stringify({ removeVolumes: false }),
      },
      { type: "tool_use_stop", id: "t1" },
      { type: "message_stop", stopReason: "tool_use" as const },
    ];
    const endTurnEvents: ProviderEvent[] = [
      { type: "text_delta", text: "Aborted." },
      { type: "message_stop", stopReason: "end_turn" as const },
    ];
    const events = await collectEvents(
      "destroy all stacks",
      { perCall: [destroyToolEvents, endTurnEvents] },
      [{ kind: "typed_confirm_value", value: "WRONG PHRASE" }],
    );
    expect(events.some((e) => e.type === "tool_result" && e.name === "destroy_all_stacks")).toBe(
      false,
    );
  });

  test("react: tool that needs permission → denied → no tool_result", async () => {
    const permToolEvents: ProviderEvent[] = [
      { type: "tool_use_start", id: "t1", name: "pull_image" },
      {
        type: "tool_use_delta",
        id: "t1",
        argsPartialJson: JSON.stringify({ image: "nginx:1.27" }),
      },
      { type: "tool_use_stop", id: "t1" },
      { type: "message_stop", stopReason: "end_turn" as const },
    ];
    const endTurnEvents: ProviderEvent[] = [
      { type: "text_delta", text: "Alright." },
      { type: "message_stop", stopReason: "end_turn" as const },
    ];
    const events = await collectEvents("pull nginx", { perCall: [permToolEvents, endTurnEvents] }, [
      { kind: "deny" },
    ]);
    expect(events.some((e) => e.type === "tool_result" && e.name === "pull_image")).toBe(false);
  });

  test("react: always_allow_in_session → permission auto-granted, tool runs", async () => {
    const toolEvents: ProviderEvent[] = [
      { type: "tool_use_start", id: "t1", name: "pull_image" },
      {
        type: "tool_use_delta",
        id: "t1",
        argsPartialJson: JSON.stringify({ image: "nginx:1.27" }),
      },
      { type: "tool_use_stop", id: "t1" },
      { type: "message_stop", stopReason: "end_turn" as const },
    ];
    const endTurnEvents: ProviderEvent[] = [
      { type: "text_delta", text: "Done." },
      { type: "message_stop", stopReason: "end_turn" as const },
    ];
    const events = await collectEvents(
      "pull nginx image",
      { perCall: [toolEvents, endTurnEvents] },
      [{ kind: "always_allow_in_session" }],
    );
    expect(events.some((e) => e.type === "tool_result" && e.name === "pull_image")).toBe(true);
  });

  test("unknown tool → continues to next iteration", async () => {
    const toolEvents: ProviderEvent[] = [
      { type: "tool_use_start", id: "t1", name: "nonexistent_tool" },
      { type: "tool_use_stop", id: "t1" },
      { type: "message_stop", stopReason: "end_turn" as const },
    ];
    const endTurnEvents: ProviderEvent[] = [
      { type: "text_delta", text: "I cannot do that." },
      { type: "message_stop", stopReason: "end_turn" as const },
    ];
    const events = await collectEvents(
      "check status",
      { perCall: [toolEvents, endTurnEvents] },
      [],
    );
    expect(events.some((e) => e.type === "tool_result" && e.name === "nonexistent_tool")).toBe(
      false,
    );
    const texts = events
      .filter((e): e is { type: "assistant_text"; delta: string } => e.type === "assistant_text")
      .map((e) => e.delta)
      .join("");
    expect(texts).toContain("I cannot do that");
  });

  test("max iterations → error event", async () => {
    const iteration: ProviderEvent[] = [
      { type: "tool_use_start", id: "t1", name: "list_stacks" },
      { type: "tool_use_delta", id: "t1", argsPartialJson: "{}" },
      { type: "tool_use_stop", id: "t1" },
      { type: "message_stop", stopReason: "end_turn" as const },
    ];
    const manyIterations: ProviderEvent[][] = [];
    for (let i = 0; i < 9; i++) manyIterations.push([...iteration]);
    manyIterations.push([
      { type: "text_delta", text: "done" },
      { type: "message_stop", stopReason: "end_turn" as const },
    ]);
    const responses: PermissionResponse[] = [];
    for (let i = 0; i < 9; i++) responses.push({ kind: "approve" });
    const events = await collectEvents("list stacks", { perCall: manyIterations }, responses);
    const errorEv = events.find((e) => e.type === "error");
    expect(errorEv).toBeDefined();
    expect((errorEv as { error: Error }).error.message).toContain("max iterations");
  });
});
