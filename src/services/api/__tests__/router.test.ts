import { describe, expect, test } from "vitest";
import { resolveProviderForRequest } from "src/services/api";

describe("provider router", () => {
  test("returns the requested provider by name", () => {
    const p = resolveProviderForRequest("ollama", { OLLAMA_MODEL: "qwen2.5:14b" });
    expect(p.name).toBe("ollama");
  });

  test("returns gemini by default", () => {
    const p = resolveProviderForRequest("gemini", { GEMINI_API_KEY: "fake" });
    expect(p.name).toBe("gemini");
  });

  test("throws on unknown provider", () => {
    expect(() => resolveProviderForRequest("unknown" as never, {})).toThrow(/unknown provider/i);
  });
});