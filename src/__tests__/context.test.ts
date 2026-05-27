import { buildSystemPrompt, classifyIntent } from "src/context";
import { describe, expect, test } from "vitest";

describe("intent classifier", () => {
  test("Vietnamese 'tạo' triggers plan-once", () => {
    expect(classifyIntent("tạo nginx server")).toBe("plan-once");
  });

  test("English 'create' triggers plan-once", () => {
    expect(classifyIntent("create a postgres database")).toBe("plan-once");
  });

  test("status query → react", () => {
    expect(classifyIntent("show status of webapp")).toBe("react");
  });

  test("destroy → react", () => {
    expect(classifyIntent("destroy webapp")).toBe("react");
  });
});

describe("buildSystemPrompt", () => {
  test("plan-once prompt contains plan_stack instructions and state summary", () => {
    const p = buildSystemPrompt("plan-once", "stacks: {}\n");
    expect(p).toContain("plan_stack");
    expect(p).toContain("stacks: {}");
  });

  test("react prompt lists available tools and instructs ReAct loop", () => {
    const p = buildSystemPrompt("react", "stacks: {}\n");
    expect(p).toContain("ReAct");
    expect(p).toContain("inspect_drift");
  });
});
