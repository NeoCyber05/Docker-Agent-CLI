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

  test("'build a' multi-word keyword triggers plan-once", () => {
    expect(classifyIntent("build a postgres server")).toBe("plan-once");
  });

  test("mixed-case Vietnamese triggers plan-once", () => {
    expect(classifyIntent("Tạo nginx")).toBe("plan-once");
  });

  test("uppercase 'DEPLOY' triggers plan-once", () => {
    expect(classifyIntent("DEPLOY my app")).toBe("plan-once");
  });
});

describe("buildSystemPrompt", () => {
  test("plan-once prompt contains plan_stack instructions and state summary", () => {
    const p = buildSystemPrompt("plan-once", "stacks: {}\n");
    expect(p).toContain("plan_stack");
    expect(p).toContain("stacks: {}");
    expect(p).not.toContain("{{STATE_SUMMARY}}");
  });

  test("react prompt lists available tools and instructs ReAct loop", () => {
    const p = buildSystemPrompt("react", "stacks: {}\n");
    expect(p).toContain("ReAct");
    expect(p).toContain("inspect_drift");
    expect(p).not.toContain("{{STATE_SUMMARY}}");
  });

  test("empty stateSummary falls back to (none)", () => {
    const p = buildSystemPrompt("react", "");
    expect(p).toContain("(none)");
    expect(p).not.toContain("{{STATE_SUMMARY}}");
  });

  test("whitespace-only stateSummary falls back to (none)", () => {
    const p = buildSystemPrompt("plan-once", "   \n  ");
    expect(p).toContain("(none)");
  });
});
