import { getAgentTools, getAllTools } from "src/tools";
import { describe, expect, test } from "vitest";

describe("tool registry", () => {
  test("getAllTools returns 15 tools", () => {
    expect(getAllTools()).toHaveLength(15);
  });

  test("getAgentTools returns 14 LLM-exposed tools", () => {
    expect(getAgentTools()).toHaveLength(14);
  });

  test("getAgentTools includes plan_stack but never apply_stack", () => {
    const names = getAgentTools().map((tool) => tool.name);
    expect(names).toContain("plan_stack");
    expect(names).not.toContain("apply_stack");
    expect(names).toContain("destroy_stack");
    expect(names).toContain("destroy_all_stacks");
  });

  test("getAllTools includes apply_stack for internal dispatch", () => {
    const names = getAllTools().map((tool) => tool.name);
    expect(names).toContain("apply_stack");
  });
});
