import { describe, expect, test } from "vitest";
import { AgentState } from "./state";

describe("AgentState annotation", () => {
  test("exposes messages, iter, allowSet, pendingToolResults", () => {
    expect(AgentState.messages).toBeDefined();
    expect(AgentState.iter).toBeDefined();
    expect(AgentState.allowSet).toBeDefined();
    expect(AgentState.pendingToolResults).toBeDefined();
  });
});
