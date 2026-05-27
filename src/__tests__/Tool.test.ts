import { type Tool, findToolByName } from "src/Tool";
import { describe, expect, test } from "vitest";

describe("Tool registry helpers", () => {
  test("findToolByName matches by name", () => {
    const a: Tool = {
      name: "alpha",
      description: "",
      inputSchema: { parse: (x: unknown) => x } as never,
      category: "read-only",
      needsPermission: () => false,
      call: async function* () {
        yield { type: "progress", msg: "noop" };
        return undefined;
      },
    };
    expect(findToolByName([a], "alpha")).toBe(a);
    expect(findToolByName([a], "beta")).toBeUndefined();
  });
});
