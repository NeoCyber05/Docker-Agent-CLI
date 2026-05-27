import { describe, expect, test } from "vitest";
import type {
  AssistantMessage,
  Message,
  ToolResultMessage,
  UserMessage,
} from "src/types/message";
import type { LoopEvent, PermissionResponse } from "src/types/events";
import type { StackDefinition } from "src/types/stack";

describe("type shape sanity", () => {
  test("Message union accepts all three roles", () => {
    const u: UserMessage = { role: "user", content: "hi" };
    const a: AssistantMessage = { role: "assistant", content: [{ type: "text", text: "ok" }] };
    const t: ToolResultMessage = {
      role: "tool",
      toolUseId: "abc",
      content: "ran",
      isError: false,
    };
    const all: Message[] = [u, a, t];
    expect(all).toHaveLength(3);
  });

  test("PermissionResponse discriminated union", () => {
    const r: PermissionResponse = { kind: "approve" };
    const r2: PermissionResponse = { kind: "secrets_input_values", values: { K: "v" } };
    expect([r, r2]).toHaveLength(2);
  });

  test("LoopEvent secrets_input_request shape", () => {
    const ev: LoopEvent = {
      type: "secrets_input_request",
      id: "x",
      service: "db",
      keys: ["POSTGRES_PASSWORD"],
      reason: "missing required env",
    };
    expect(ev.type).toBe("secrets_input_request");
  });

  test("StackDefinition has services map and x-docker-agent metadata", () => {
    const def: StackDefinition = {
      "x-docker-agent": {
        name: "webapp",
        createdAt: "2026-05-26T10:00:00Z",
        lastApplied: null,
        intent: "demo",
        provider: "gemini",
        generatedBy: "gemini-2.0-flash-exp",
        envFileSources: {},
      },
      services: { nginx: { image: "nginx:1.27" } },
    };
    expect(def.services.nginx?.image).toBe("nginx:1.27");
  });
});
