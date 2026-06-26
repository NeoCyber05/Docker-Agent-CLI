import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { nanoid } from "nanoid";
import type { LoopContext } from "src/loopContext";
import type { Provider, ProviderEvent } from "src/services/api/types";
import type { ComposeRunner } from "src/services/docker/composeRunner";
import type { EngineClient } from "src/services/docker/engineClient";
import { StateStore } from "src/state/StateStore";
import type { LoopEvent } from "src/types/events";
import type { PermissionResponse } from "src/types/permissions";
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

function makeContext(
  tmp: string,
  opts: {
    emit?: (ev: LoopEvent) => void;
    permissionResponse?: PermissionResponse;
    allowSet?: Set<string>;
  } = {},
): LoopContext {
  return {
    cwd: tmp,
    stateStore: new StateStore(tmp),
    dockerEngine: new MockDockerEngine() as unknown as EngineClient,
    composeRunner: new MockComposeRunner(tmp) as unknown as ComposeRunner,
    abortSignal: new AbortController().signal,
    requestPermission: async (tool, input) => {
      opts.emit?.({ type: "permission_request", id: nanoid(), tool, input });
      return opts.permissionResponse ?? { kind: "approve" as const };
    },
    requestConfirm: async () => ({ kind: "approve" as const }),
    requestTypedConfirm: async () => ({ kind: "typed_confirm_value" as const, value: "x" }),
    requestSecretsInput: async () => ({ kind: "deny" as const }),
    allowSet: opts.allowSet ?? new Set<string>(),
  };
}

function toolUseCall(toolName: string, input: unknown): ProviderEvent[] {
  const inputJson = JSON.stringify(input);
  return [
    { type: "tool_use_start", id: "t1", name: toolName },
    { type: "tool_use_delta", id: "t1", argsPartialJson: inputJson },
    { type: "tool_use_stop", id: "t1" },
    { type: "message_stop", stopReason: "tool_use" },
  ];
}

function textDone(): ProviderEvent[] {
  return [
    { type: "text_delta", text: "done" },
    { type: "message_stop", stopReason: "end_turn" },
  ];
}

async function runBackend(
  tmp: string,
  toolName: string,
  input: unknown,
  ctx?: LoopContext,
): Promise<LoopEvent[]> {
  const events: LoopEvent[] = [];
  const context = ctx ?? makeContext(tmp, { emit: (ev) => events.push(ev) });
  const backend = new LangGraphBackend();
  for await (const ev of backend.query({
    messages: [{ role: "user", content: `run ${toolName}` }],
    ctx: context,
    provider: fakeProvider([toolUseCall(toolName, input), textDone()]) as unknown as Provider,
  })) {
    events.push(ev);
  }
  return events;
}

async function runToolTest(params: {
  tmp: string;
  toolName: string;
  input: unknown;
  expectPermissionRequest?: boolean;
}): Promise<{ events: LoopEvent[]; toolResult: LoopEvent & { type: "tool_result" } }> {
  const events = await runBackend(params.tmp, params.toolName, params.input);

  const types = events.map((e) => e.type);
  expect(types).toContain("iteration_start");
  expect(types).toContain("tool_call");
  expect(types).toContain("tool_result");

  if (params.expectPermissionRequest) {
    expect(types).toContain("permission_request");
  }

  const toolResult = events.find(
    (e): e is LoopEvent & { type: "tool_result" } => e.type === "tool_result",
  );
  expect(toolResult).toBeDefined();
  if (!toolResult) {
    throw new Error("expected tool_result event to be present");
  }
  return { events, toolResult };
}

function expectEventOrder(events: LoopEvent[], ...types: LoopEvent["type"][]) {
  const indices = types.map((t) => events.findIndex((e) => e.type === t));
  for (let i = 0; i < indices.length - 1; i++) {
    const current = indices[i];
    const next = indices[i + 1];
    if (current === undefined || next === undefined) {
      throw new Error("unexpected undefined event index");
    }
    expect(current).toBeGreaterThanOrEqual(0);
    expect(current).toBeLessThan(next);
  }
}

describe("toolsNode read-only parity", () => {
  let tmp: string;
  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "lgpar-"));
    fs.writeFileSync(path.join(tmp, "project-policies.yaml"), "project: {}");
  });
  afterEach(() => fs.rmSync(tmp, { recursive: true, force: true }));

  test("validate_spec emits tool_call + tool_result", async () => {
    const { toolResult } = await runToolTest({
      tmp,
      toolName: "validate_spec",
      input: {
        services: [{ name: "web", kind: "custom", image: "nginx:latest" }],
      },
    });
    expect(typeof toolResult.output).toBe("object");
    expect((toolResult.output as { valid: boolean }).valid).toBe(true);
  });

  test("resolve_dependency emits tool_call + tool_result", async () => {
    const { toolResult } = await runToolTest({
      tmp,
      toolName: "resolve_dependency",
      input: {
        services: [
          { name: "web", kind: "custom", image: "nginx:latest", depends_on: ["db"] },
          { name: "db", kind: "catalog", catalogId: "redis:7" },
        ],
      },
    });
    expect(typeof toolResult.output).toBe("object");
    expect((toolResult.output as { valid: boolean }).valid).toBe(true);
  });

  test("check_port_conflict emits tool_call + tool_result", async () => {
    await runToolTest({
      tmp,
      toolName: "check_port_conflict",
      input: {
        services: [
          {
            name: "web",
            kind: "custom",
            image: "nginx:latest",
            exposure: "public",
            containerPort: 80,
          },
        ],
      },
    });
  });

  test("list_stacks emits tool_call + tool_result", async () => {
    const { toolResult } = await runToolTest({ tmp, toolName: "list_stacks", input: {} });
    expect(typeof toolResult.output).toBe("object");
    expect(Array.isArray((toolResult.output as { stacks: unknown[] }).stacks)).toBe(true);
  });

  test("inspect_drift emits tool_call + tool_result", async () => {
    await runToolTest({ tmp, toolName: "inspect_drift", input: { stackName: "test" } });
  });

  test("get_stack_status emits tool_call + tool_result", async () => {
    const { toolResult } = await runToolTest({
      tmp,
      toolName: "get_stack_status",
      input: { stackName: "test" },
    });
    expect(typeof toolResult.output).toBe("object");
    expect((toolResult.output as { rows: unknown; logTail: unknown }).rows).toBeDefined();
  });

  test("get_health emits tool_call + tool_result", async () => {
    const { toolResult } = await runToolTest({
      tmp,
      toolName: "get_health",
      input: { stackName: "test" },
    });
    expect(typeof toolResult.output).toBe("object");
  });

  test("get_logs emits tool_call + tool_result", async () => {
    await runToolTest({ tmp, toolName: "get_logs", input: { stackName: "test" } });
  });

  test("pull_image emits permission_request + tool_call + tool_result", async () => {
    const { events, toolResult } = await runToolTest({
      tmp,
      toolName: "pull_image",
      input: { image: "nginx:latest" },
      expectPermissionRequest: true,
    });
    expectEventOrder(events, "permission_request", "tool_call", "tool_result");
  });

  test("exec_docker emits permission_request + tool_call + tool_result", async () => {
    const { events, toolResult } = await runToolTest({
      tmp,
      toolName: "exec_docker",
      input: { args: ["ps"] },
      expectPermissionRequest: true,
    });
    expectEventOrder(events, "permission_request", "tool_call", "tool_result");
  });
});

describe("toolsNode negative paths", () => {
  let tmp: string;
  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "lgpar-"));
    fs.writeFileSync(path.join(tmp, "project-policies.yaml"), "project: {}");
  });
  afterEach(() => fs.rmSync(tmp, { recursive: true, force: true }));

  test("permission denied emits permission_request but no tool_call or tool_result", async () => {
    const events: LoopEvent[] = [];
    const ctx = makeContext(tmp, {
      emit: (ev) => events.push(ev),
      permissionResponse: { kind: "deny" },
    });
    const collected = await runBackend(tmp, "exec_docker", { args: ["ps"] }, ctx);
    events.push(...collected);

    const types = events.map((e) => e.type);
    expect(types).toContain("permission_request");
    expect(types).not.toContain("tool_call");
    expect(types).not.toContain("tool_result");
  });

  test("always_allow_in_session skips permission_request on second call", async () => {
    const events: LoopEvent[] = [];
    const allowSet = new Set<string>();
    const ctx = makeContext(tmp, {
      emit: (ev) => events.push(ev),
      permissionResponse: { kind: "always_allow_in_session" },
      allowSet,
    });

    // First call: permission_request is emitted and allowSet updated.
    const first = await runBackend(tmp, "exec_docker", { args: ["ps"] }, ctx);
    events.push(...first);
    expect(events.map((e) => e.type)).toContain("permission_request");
    expect(allowSet.has("exec_docker")).toBe(true);

    // Second call in same session: no permission_request.
    const second = await runBackend(tmp, "exec_docker", { args: ["ps"] }, ctx);
    events.push(...second);
    expect(second.map((e) => e.type)).not.toContain("permission_request");
    expect(second.map((e) => e.type)).toContain("tool_call");
    expect(second.map((e) => e.type)).toContain("tool_result");
  });

  test("mutating tool outside allowlist emits no tool_call or tool_result", async () => {
    const events = await runBackend(tmp, "destroy_stack", { stackName: "test" });
    const types = events.map((e) => e.type);
    expect(types).not.toContain("tool_call");
    expect(types).not.toContain("tool_result");
    expect(types).not.toContain("permission_request");
  });

  test("unknown tool emits no tool_call or tool_result", async () => {
    const events = await runBackend(tmp, "unknown_tool_xyz", {});
    const types = events.map((e) => e.type);
    expect(types).not.toContain("tool_call");
    expect(types).not.toContain("tool_result");
  });

  test("schema validation failure emits no tool_call or tool_result", async () => {
    const events = await runBackend(tmp, "get_health", {});
    const types = events.map((e) => e.type);
    expect(types).not.toContain("tool_call");
    expect(types).not.toContain("tool_result");
  });
});
