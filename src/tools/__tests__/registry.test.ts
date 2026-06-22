import { getAgentTools, getAllTools } from "src/tools";
import { describe, expect, test } from "vitest";

describe("tool registry", () => {
  test("getAllTools includes get_logs and get_health", () => {
    const names = getAllTools().map((t) => t.name);
    expect(names).toContain("get_logs");
    expect(names).toContain("get_health");
  });

  test("getAgentTools exposes get_logs and get_health", () => {
    const names = getAgentTools().map((t) => t.name);
    expect(names).toContain("get_logs");
    expect(names).toContain("get_health");
  });

  test("getAgentTools does not expose apply_stack", () => {
    const names = getAgentTools().map((t) => t.name);
    expect(names).not.toContain("apply_stack");
  });
});
