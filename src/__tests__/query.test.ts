import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { LoopContext } from "src/loopContext";
import { query } from "src/query";
import type { CallModelParams, Provider, ProviderEvent } from "src/services/api/types";
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

function recordingProvider(perCall: ProviderEvent[][]): {
  provider: Provider;
  calls: CallModelParams[];
} {
  const calls: CallModelParams[] = [];
  let index = 0;
  return {
    calls,
    provider: {
      name: "recording",
      stream: async function* (params) {
        calls.push({
          messages: structuredClone(params.messages),
          system: params.system,
          ...(params.model ? { model: params.model } : {}),
          tools: params.tools,
          ...(params.signal ? { signal: params.signal } : {}),
        } as CallModelParams);
        for (const event of perCall[index++] ?? []) yield event;
      },
    },
  };
}

async function collectEventsWithProvider(
  userInput: string,
  provider: Provider,
  responses: PermissionResponse[],
) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "loop-"));
  fs.mkdirSync(path.join(tmp, ".docker-agent"), { recursive: true });
  fs.writeFileSync(path.join(tmp, ".docker-agent", "policies.yaml"), "project: {}");
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
    healthCheckDeadlineMs: 0,
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
    provider,
  })) {
    collected.push(ev);
  }
  fs.rmSync(tmp, { recursive: true, force: true });
  return collected;
}

async function collectEvents(
  userInput: string,
  providerParam: { events?: ProviderEvent[]; perCall?: ProviderEvent[][] },
  responses: PermissionResponse[],
) {
  const provider = providerParam.perCall
    ? multiCallProvider(providerParam.perCall)
    : fakeProvider(providerParam.events as ProviderEvent[]);
  return collectEventsWithProvider(userInput, provider as Provider, responses);
}

function makeToolEvents(id: string, name: string, input: object): ProviderEvent[] {
  return [
    { type: "tool_use_start", id, name },
    { type: "tool_use_delta", id, argsPartialJson: JSON.stringify(input) },
    { type: "tool_use_stop", id },
    { type: "message_stop", stopReason: "tool_use" as const },
  ];
}

function makePlanStackToolEvents(id: string, input: object): ProviderEvent[] {
  return makeToolEvents(id, "plan_stack", input);
}

describe("query core loop", () => {
  test("react appends an action and observation before the next reason step", async () => {
    const scripted = recordingProvider([
      [
        { type: "tool_use_start", id: "list-1", name: "list_stacks" },
        { type: "tool_use_delta", id: "list-1", argsPartialJson: "{}" },
        { type: "tool_use_stop", id: "list-1" },
        { type: "message_stop", stopReason: "tool_use" },
      ],
      [
        { type: "text_delta", text: "No stacks are defined." },
        { type: "message_stop", stopReason: "end_turn" },
      ],
    ]);

    await collectEventsWithProvider("list stacks", scripted.provider, []);

    expect(scripted.calls).toHaveLength(2);
    expect(scripted.calls[1]?.messages).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ role: "assistant" }),
        expect.objectContaining({ role: "tool", toolUseId: "list-1" }),
      ]),
    );
  });

  test("deploy observes plan_stack result before producing its final answer", async () => {
    const scripted = recordingProvider([
      makePlanStackToolEvents("plan-1", {
        stackName: "web",
        intent: "create nginx",
        services: [{ name: "web", kind: "custom", image: "nginx:1.27-alpine" }],
      }),
      [
        { type: "text_delta", text: "Deployment completed." },
        { type: "message_stop", stopReason: "end_turn" },
      ],
    ]);

    const events = await collectEventsWithProvider("create nginx", scripted.provider, [
      { kind: "approve" },
    ]);

    expect(scripted.calls).toHaveLength(2);
    expect(scripted.calls[1]?.messages.at(-1)).toMatchObject({
      role: "tool",
      toolUseId: "plan-1",
    });
    expect(events).toContainEqual({ type: "assistant_text", delta: "Deployment completed." });
  });

  test("max_tokens stops the loop with an explicit error", async () => {
    const events = await collectEvents(
      "list stacks",
      { events: [{ type: "message_stop", stopReason: "max_tokens" }] },
      [],
    );
    expect(events.find((event) => event.type === "error")).toMatchObject({
      error: expect.objectContaining({ message: expect.stringContaining("max tokens") }),
    });
  });

  test("deploy performs preflight actions, observes each result, plans, then summarizes", async () => {
    const draft = {
      services: [
        { name: "api", kind: "custom", image: "example/api:1", exposure: "public", containerPort: 80, depends_on: ["db"] },
        { name: "db", kind: "catalog", catalogId: "postgresql:16" },
      ],
    };
    const scripted = recordingProvider([
      makeToolEvents("validate-1", "validate_spec", draft),
      makeToolEvents("dependency-1", "resolve_dependency", draft),
      makeToolEvents("port-1", "check_port_conflict", { stackName: "app", ...draft }),
      makePlanStackToolEvents("plan-1", {
        stackName: "app",
        intent: "deploy app",
        ...draft,
      }),
      [
        { type: "text_delta", text: "Stack app was applied." },
        { type: "message_stop", stopReason: "end_turn" },
      ],
    ]);

    const events = await collectEventsWithProvider("deploy app", scripted.provider, [
      { kind: "approve" },
    ]);

    expect(scripted.calls).toHaveLength(5);
    for (const id of ["validate-1", "dependency-1", "port-1", "plan-1"]) {
      expect(scripted.calls.at(-1)?.messages).toEqual(
        expect.arrayContaining([expect.objectContaining({ role: "tool", toolUseId: id })]),
      );
    }
    expect(events.at(-1)).toEqual({ type: "assistant_text", delta: "Stack app was applied." });
  });

  test("deploy: provider emits plan_stack tool_use → tool_result for plan_stack + apply_stack on approve", async () => {
    const events = await collectEvents(
      "tạo nginx",
      {
        events: makePlanStackToolEvents("t1", {
          stackName: "test",
          intent: "nginx",
          services: [{ name: "web", kind: "custom", image: "nginx:1.27-alpine" }],
        }),
      },
      [{ kind: "approve" }],
    );
    expect(events.some((e) => e.type === "tool_result" && e.name === "plan_stack")).toBe(true);
    expect(events.some((e) => e.type === "tool_result" && e.name === "apply_stack")).toBe(true);
  });

  test("deploy: user declines plan → no apply_stack tool_result", async () => {
    const events = await collectEvents(
      "create app",
      {
        events: makePlanStackToolEvents("t1", {
          stackName: "test",
          intent: "app",
          services: [{ name: "web", kind: "custom", image: "nginx:1.27-alpine" }],
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

  test("direct destroy-stack command bypasses provider planning", async () => {
    const recorded = recordingProvider([
      [
        { type: "text_delta", text: "I will destroy the stack." },
        { type: "message_stop", stopReason: "end_turn" as const },
      ],
    ]);

    const events = await collectEventsWithProvider("Destroy stack webapp", recorded.provider, [
      { kind: "approve" },
    ]);

    expect(recorded.calls).toHaveLength(0);
    expect(
      events.some((event) => event.type === "tool_call" && event.name === "destroy_stack"),
    ).toBe(true);
    expect(
      events.some((event) => event.type === "tool_result" && event.name === "destroy_stack"),
    ).toBe(true);
  });

  test("direct destroy-stack permission denied → no tool_result", async () => {
    const recorded = recordingProvider([]);

    const events = await collectEventsWithProvider("Destroy stack webapp", recorded.provider, [
      { kind: "deny" },
    ]);

    expect(recorded.calls).toHaveLength(0);
    expect(
      events.some((event) => event.type === "tool_result" && event.name === "destroy_stack"),
    ).toBe(false);
    const texts = events
      .filter((e): e is { type: "assistant_text"; delta: string } => e.type === "assistant_text")
      .map((e) => e.delta)
      .join("");
    expect(texts).toContain("permission denied");
  });

  test("direct destroy-all command bypasses provider planning", async () => {
    const recorded = recordingProvider([
      [
        { type: "text_delta", text: "I will update the existing stack." },
        { type: "message_stop", stopReason: "end_turn" as const },
      ],
    ]);

    const events = await collectEventsWithProvider("Destroy all stacks", recorded.provider, [
      { kind: "typed_confirm_value", value: "DESTROY ALL" },
    ]);

    expect(recorded.calls).toHaveLength(0);
    expect(
      events.some((event) => event.type === "tool_call" && event.name === "destroy_all_stacks"),
    ).toBe(true);
    expect(events.some((event) => event.type === "tool_call" && event.name === "plan_stack")).toBe(
      false,
    );
  });

  test("direct destroy-all command is case-insensitive", async () => {
    const recorded = recordingProvider([]);

    const events = await collectEventsWithProvider("destroy all stacks", recorded.provider, [
      { kind: "typed_confirm_value", value: "DESTROY ALL" },
    ]);

    expect(recorded.calls).toHaveLength(0);
    expect(
      events.some((event) => event.type === "tool_call" && event.name === "destroy_all_stacks"),
    ).toBe(true);
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
    // Push 25 tool-use iterations (> maxIterations=24 for react mode) so the loop hits the cap
    for (let i = 0; i < 25; i++) manyIterations.push([...iteration]);
    manyIterations.push([
      { type: "text_delta", text: "done" },
      { type: "message_stop", stopReason: "end_turn" as const },
    ]);
    const responses: PermissionResponse[] = [];
    for (let i = 0; i < 25; i++) responses.push({ kind: "approve" });
    const events = await collectEvents("list stacks", { perCall: manyIterations }, responses);
    const errorEv = events.find((e) => e.type === "error");
    expect(errorEv).toBeDefined();
    expect((errorEv as { error: Error }).error.message).toContain(
      "agent loop reached max iterations",
    );
  });

  test("plan_stack blocks execution on Policy violations", async () => {
    // 1. Create a global policy file requiring healthchecks
    const globalPolicyPath = path.join(os.homedir(), ".docker-agent", "policies.yaml");
    const origGlobalPolicy = fs.existsSync(globalPolicyPath) ? fs.readFileSync(globalPolicyPath, "utf-8") : null;
    fs.mkdirSync(path.dirname(globalPolicyPath), { recursive: true });
    fs.writeFileSync(
      globalPolicyPath,
      `
global:
  require:
    - healthcheck:
        required: true
      `,
    );

    const planStackEvents: ProviderEvent[] = [
      { type: "tool_use_start", id: "t1", name: "plan_stack" },
      {
        type: "tool_use_delta",
        id: "t1",
        argsPartialJson: JSON.stringify({
          stackName: "app",
          intent: "deploy app",
          services: [
            { name: "web", kind: "custom", image: "nginx:latest" } // lacks healthcheck
          ]
        }),
      },
      { type: "tool_use_stop", id: "t1" },
      { type: "message_stop", stopReason: "tool_use" as const },
    ];

    try {
      const events = await collectEvents(
        "deploy stack app",
        { events: planStackEvents },
        [],
      );

      // plan_stack tool itself runs
      const toolResult = events.find((e) => e.type === "tool_result" && e.name === "plan_stack");
      expect(toolResult).toBeDefined();

      // but apply_stack is blocked
      const applyResult = events.find((e) => e.type === "tool_result" && e.name === "apply_stack");
      expect(applyResult).toBeUndefined();
    } finally {
      // restore original global policy
      if (origGlobalPolicy !== null) {
        fs.writeFileSync(globalPolicyPath, origGlobalPolicy);
      } else {
        try { fs.unlinkSync(globalPolicyPath); } catch {}
      }
    }
  });

  test("destroy_stack with removeVolumes requires typed confirmation", async () => {
    const scripted = recordingProvider([
      [
        { type: "tool_use_start", id: "t1", name: "destroy_stack" },
        {
          type: "tool_use_delta",
          id: "t1",
          argsPartialJson: JSON.stringify({
            stackName: "app",
            removeVolumes: true,
          }),
        },
        { type: "tool_use_stop", id: "t1" },
        { type: "message_stop", stopReason: "tool_use" },
      ],
      [
        { type: "text_delta", text: "Aborted." },
        { type: "message_stop", stopReason: "end_turn" },
      ]
    ]);

    const events = await collectEventsWithProvider(
      "delete stack app with volumes",
      scripted.provider,
      [{ kind: "typed_confirm_value", value: "WRONG PHRASE" }],
    );

    // Verify destroy_stack was aborted and the message was sent to the provider
    expect(scripted.calls).toHaveLength(2);
    expect(scripted.calls[1]?.messages).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          role: "tool",
          toolUseId: "t1",
          content: "destroy_stack aborted: typed confirmation did not match",
        }),
      ]),
    );

    // Also verify destroyStack tool did not execute
    const toolResult = events.find((e) => e.type === "tool_result" && e.name === "destroy_stack");
    expect(toolResult).toBeUndefined();
  });
});
