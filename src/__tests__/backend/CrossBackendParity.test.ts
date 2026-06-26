import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { nanoid } from "nanoid";
import type { LoopContext } from "src/loopContext";
import type { ProviderEvent } from "src/services/api/types";
import type { ComposeRunner } from "src/services/docker/composeRunner";
import type { EngineClient } from "src/services/docker/engineClient";
import { StateStore } from "src/state/StateStore";
import type { LoopEvent } from "src/types/events";
import type { PermissionResponse } from "src/types/permissions";
import { afterEach, beforeEach, describe, expect, test } from "vitest";
import { MockComposeRunner } from "../../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../../tests/mocks/mockDockerEngine";

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

function createTestContext(
  tmp: string,
  opts: {
    emit?: (ev: LoopEvent) => void;
    permissionResponse?: PermissionResponse;
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
    allowSet: new Set<string>(),
  };
}

async function runBackend(params: {
  messages: { role: "user"; content: string }[];
  ctx: LoopContext;
  provider: ReturnType<typeof fakeProvider>;
}): Promise<LoopEvent[]> {
  const { createBackend } = await import("src/backend/AgentBackend");
  const backend = await createBackend();
  const events: LoopEvent[] = [];
  for await (const ev of backend.query({
    messages: params.messages,
    ctx: params.ctx,
    provider: params.provider,
  })) {
    events.push(ev);
  }
  return events;
}

for (const backendName of ["current", "langgraph"] as const) {
  describe(`${backendName} backend parity`, () => {
    const prevBackend = process.env.DOCKER_AGENT_BACKEND;
    let tmp: string;
    beforeEach(() => {
      process.env.DOCKER_AGENT_BACKEND = backendName;
      tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cbpar-"));
      fs.writeFileSync(path.join(tmp, "project-policies.yaml"), "project: {}");
    });
    afterEach(() => {
      process.env.DOCKER_AGENT_BACKEND = prevBackend;
      fs.rmSync(tmp, { recursive: true, force: true });
    });

    test("empty user → end_turn emits assistant_text and no tool events", async () => {
      const ctx = createTestContext(tmp);
      const events = await runBackend({
        messages: [{ role: "user", content: "hello" }],
        ctx,
        provider: fakeProvider([
          [
            { type: "text_delta", text: "hello" },
            { type: "message_stop", stopReason: "end_turn" },
          ],
        ]),
      });
      const types = events.map((e) => e.type);
      expect(types).toContain("assistant_text");
      expect(types).not.toContain("tool_call");
      expect(types).not.toContain("tool_result");
      expect(types).not.toContain("error");
    });

    test("read-only tool call emits iteration_start, tool_call, tool_result, assistant_text", async () => {
      const ctx = createTestContext(tmp);
      const events = await runBackend({
        messages: [{ role: "user", content: "list stacks" }],
        ctx,
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
        ]),
      });
      const types = events.map((e) => e.type);
      expect(types).toContain("iteration_start");
      expect(types).toContain("tool_call");
      expect(types).toContain("tool_result");
      expect(types).toContain("assistant_text");

      const toolResult = events.find(
        (e): e is LoopEvent & { type: "tool_result" } => e.type === "tool_result",
      );
      expect(toolResult).toBeDefined();
      if (!toolResult) {
        throw new Error("expected tool_result event to be present");
      }
      expect(toolResult.name).toBe("list_stacks");
      expect(typeof toolResult.output).toBe("object");
      expect(Array.isArray((toolResult.output as { stacks: unknown[] }).stacks)).toBe(true);
    });

    test("permission denied emits permission_request but no tool_call or tool_result", async () => {
      const events: LoopEvent[] = [];
      const ctx = createTestContext(tmp, {
        emit: (ev) => events.push(ev),
        permissionResponse: { kind: "deny" },
      });
      const collected = await runBackend({
        messages: [{ role: "user", content: "pull nginx" }],
        ctx,
        provider: fakeProvider([
          [
            { type: "tool_use_start", id: "t1", name: "pull_image" },
            { type: "tool_use_delta", id: "t1", argsPartialJson: '{"image":"nginx:latest"}' },
            { type: "tool_use_stop", id: "t1" },
            { type: "message_stop", stopReason: "tool_use" },
          ],
          [
            { type: "text_delta", text: "done" },
            { type: "message_stop", stopReason: "end_turn" },
          ],
        ]),
      });
      events.push(...collected);

      const types = events.map((e) => e.type);
      expect(types).toContain("permission_request");
      // CurrentBackend and LangGraphBackend both do NOT emit tool_call or
      // tool_result when permission is denied.
      expect(types).not.toContain("tool_call");
      expect(types).not.toContain("tool_result");
    });

    test("max iterations emits error and caps iteration_start at 24", async () => {
      const ctx = createTestContext(tmp);
      const iteration: ProviderEvent[] = [
        { type: "tool_use_start", id: "t1", name: "list_stacks" },
        { type: "tool_use_delta", id: "t1", argsPartialJson: "{}" },
        { type: "tool_use_stop", id: "t1" },
        { type: "message_stop", stopReason: "tool_use" },
      ];
      const calls: ProviderEvent[][] = [];
      for (let i = 0; i < 25; i++) calls.push([...iteration]);

      const events = await runBackend({
        messages: [{ role: "user", content: "list stacks forever" }],
        ctx,
        provider: fakeProvider(calls),
      });

      const errorEv = events.find((e) => e.type === "error");
      expect(errorEv).toBeDefined();
      if (!errorEv || errorEv.type !== "error") {
        throw new Error("expected error event to be present");
      }
      expect(errorEv.error.message).toMatch(/agent loop reached max iterations/);

      const iterationStarts = events.filter((e) => e.type === "iteration_start");
      expect(iterationStarts.length).toBeLessThanOrEqual(24);
    });
  });
}
