import { getAllTools, getToolsForMode } from "src/tools";
import { describe, expect, test } from "vitest";

describe("tool registry", () => {
  test("getAllTools returns 10 tools", () => {
    expect(getAllTools()).toHaveLength(10);
  });

  test("plan-once mode exposes only plan_stack", () => {
    expect(getToolsForMode("plan-once").map((tool) => tool.name)).toEqual(["plan_stack"]);
  });

  test("react mode includes plan_stack but never apply_stack", () => {
    const names = getToolsForMode("react").map((tool) => tool.name);
    expect(names).toContain("plan_stack");
    expect(names).not.toContain("apply_stack");
    expect(names).toContain("destroy_stack");
    expect(names).toContain("destroy_all_stacks");
  });
});
