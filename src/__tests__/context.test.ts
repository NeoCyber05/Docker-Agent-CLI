import { buildSystemPrompt, classifyIntent } from "src/context";
import { describe, expect, test } from "vitest";

describe("intent classifier", () => {
  test("Vietnamese 'tạo' triggers deploy", () => {
    expect(classifyIntent("tạo nginx server")).toBe("deploy");
  });

  test("English 'create' triggers deploy", () => {
    expect(classifyIntent("create a postgres database")).toBe("deploy");
  });

  test("status query → react", () => {
    expect(classifyIntent("show status of webapp")).toBe("react");
  });

  test("destroy → react", () => {
    expect(classifyIntent("destroy webapp")).toBe("react");
  });

  test("'build a' multi-word keyword triggers deploy", () => {
    expect(classifyIntent("build a postgres server")).toBe("deploy");
  });

  test("mixed-case Vietnamese triggers deploy", () => {
    expect(classifyIntent("Tạo nginx")).toBe("deploy");
  });

  test("uppercase 'DEPLOY' triggers deploy", () => {
    expect(classifyIntent("DEPLOY my app")).toBe("deploy");
  });
});

describe("buildSystemPrompt", () => {
  test("deploy prompt contains plan_stack instructions and state summary", () => {
    const p = buildSystemPrompt("deploy", "stacks: {}\n");
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
    const p = buildSystemPrompt("deploy", "   \n  ");
    expect(p).toContain("(none)");
  });
});
