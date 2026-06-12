import { getAllTools, getToolsForMode } from "src/tools";
import { describe, expect, test } from "vitest";

describe("tool registry", () => {
  test("getAllTools includes get_logs and get_health", () => {
    const names = getAllTools().map((t) => t.name);
    expect(names).toContain("get_logs");
    expect(names).toContain("get_health");
  });

  test("react mode exposes get_logs and get_health", () => {
    const names = getToolsForMode("react").map((t) => t.name);
    expect(names).toContain("get_logs");
    expect(names).toContain("get_health");
  });

  test("plan-once mode does not expose the observability tools", () => {
    const names = getToolsForMode("plan-once").map((t) => t.name);
    expect(names).not.toContain("get_logs");
    expect(names).not.toContain("get_health");
  });
});
