import { getAllTools, getToolsForMode } from "src/tools";
import { describe, expect, test } from "vitest";

describe("tool registry", () => {
  test("getAllTools returns 15 tools", () => {
    expect(getAllTools()).toHaveLength(15);
  });

  test("deploy exposes preflight observations and plan_stack only", () => {
    expect(getToolsForMode("deploy").map((tool) => tool.name)).toEqual([
      "validate_spec",
      "resolve_dependency",
      "check_port_conflict",
      "plan_stack",
    ]);
  });

  test("react mode includes plan_stack but never apply_stack", () => {
    const names = getToolsForMode("react").map((tool) => tool.name);
    expect(names).toContain("plan_stack");
    expect(names).not.toContain("apply_stack");
    expect(names).toContain("destroy_stack");
    expect(names).toContain("destroy_all_stacks");
  });
});
