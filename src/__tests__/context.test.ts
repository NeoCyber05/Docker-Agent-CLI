import { buildSystemPrompt } from "src/context";
import { describe, expect, test } from "vitest";

describe("buildSystemPrompt", () => {
  test("prompt contains plan_stack instructions and state summary", () => {
    const p = buildSystemPrompt("stacks: {}\n");
    expect(p).toContain("plan_stack");
    expect(p).toContain("stacks: {}");
    expect(p).not.toContain("{{STATE_SUMMARY}}");
  });

  test("prompt instructs tool loop and operations guidance", () => {
    const p = buildSystemPrompt("stacks: {}\n");
    expect(p).toContain("reason from the user request");
    expect(p).toContain("inspect_drift");
    expect(p).not.toContain("{{STATE_SUMMARY}}");
  });

  test("empty stateSummary falls back to (none)", () => {
    const p = buildSystemPrompt("");
    expect(p).toContain("(none)");
    expect(p).not.toContain("{{STATE_SUMMARY}}");
  });

  test("whitespace-only stateSummary falls back to (none)", () => {
    const p = buildSystemPrompt("   \n  ");
    expect(p).toContain("(none)");
  });
});
