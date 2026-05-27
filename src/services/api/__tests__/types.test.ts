import type { Provider, ProviderEvent, ToolSchema, UsageInfo } from "src/services/api/types";
import { describe, expect, test } from "vitest";

describe("ProviderEvent", () => {
  test("text_delta variant", () => {
    const ev: ProviderEvent = { type: "text_delta", text: "hi" };
    expect(ev).toStrictEqual({ type: "text_delta", text: "hi" });
    if (ev.type === "text_delta") {
      expect(ev.text).toBe("hi");
    }
  });

  test("tool_use_start variant", () => {
    const ev: ProviderEvent = { type: "tool_use_start", id: "t1", name: "plan_stack" };
    expect(ev).toStrictEqual({ type: "tool_use_start", id: "t1", name: "plan_stack" });
  });

  test("tool_use_delta carries partial JSON", () => {
    const ev: ProviderEvent = {
      type: "tool_use_delta",
      id: "abc",
      argsPartialJson: '{"key":',
    };
    expect(ev).toStrictEqual({ type: "tool_use_delta", id: "abc", argsPartialJson: '{"key":' });
  });

  test("tool_use_stop variant", () => {
    const ev: ProviderEvent = { type: "tool_use_stop", id: "t1" };
    expect(ev).toStrictEqual({ type: "tool_use_stop", id: "t1" });
  });

  test("message_stop variant", () => {
    const ev: ProviderEvent = { type: "message_stop", stopReason: "end_turn" };
    expect(ev).toStrictEqual({ type: "message_stop", stopReason: "end_turn" });
  });

  test("usage carries token counts", () => {
    const u: UsageInfo = { inputTokens: 100, outputTokens: 50 };
    const ev: ProviderEvent = { type: "usage", ...u };
    expect(ev).toStrictEqual({ type: "usage", inputTokens: 100, outputTokens: 50 });
  });

  test("error variant", () => {
    const err = new Error("boom");
    const ev: ProviderEvent = { type: "error", error: err };
    expect(ev.type).toBe("error");
    expect(ev.error.message).toBe("boom");
  });
});

describe("ToolSchema", () => {
  test("has name, description, inputSchema", () => {
    const ts: ToolSchema = {
      name: "plan_stack",
      description: "Generates a compose plan",
      inputSchema: { type: "object" },
    };
    expect(ts.name).toBe("plan_stack");
    expect(ts.description).toBe("Generates a compose plan");
    expect(ts.inputSchema).toEqual({ type: "object" });
  });
});

describe("Provider interface", () => {
  test("stream returns AsyncGenerator of ProviderEvent", () => {
    const provider: Provider = {
      stream: async function* () {
        yield { type: "text_delta", text: "hello" };
      },
    };
    expect(provider.stream).toBeTypeOf("function");
  });
});
