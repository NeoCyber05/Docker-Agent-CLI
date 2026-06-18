import { MemoryApiKeyStore } from "src/secrets/apiKeyStore";
import type { Provider } from "src/services/api/types";
import { getProviderStatuses } from "src/services/providerStatus";
import { describe, expect, it, vi } from "vitest";

describe("getProviderStatuses", () => {
  it("marks gemini connected when env key present", async () => {
    const prev = process.env.GEMINI_API_KEY;
    process.env.GEMINI_API_KEY = "test-key";
    try {
      const statuses = await getProviderStatuses({
        apiKeyStore: new MemoryApiKeyStore(),
        providers: {
          ollama: { name: "ollama", stream: vi.fn(), listModels: vi.fn().mockResolvedValue([]) },
        },
      });
      expect(statuses.find((s) => s.provider === "gemini")).toMatchObject({ connected: true });
    } finally {
      if (prev === undefined) Reflect.deleteProperty(process.env, "GEMINI_API_KEY");
      else process.env.GEMINI_API_KEY = prev;
    }
  });

  it("marks ollama connected when listModels succeeds", async () => {
    const statuses = await getProviderStatuses({
      apiKeyStore: new MemoryApiKeyStore(),
      providers: {
        ollama: {
          name: "ollama",
          stream: vi.fn(),
          listModels: vi.fn().mockResolvedValue(["qwen2.5:14b"]),
        },
      },
    });
    expect(statuses.find((s) => s.provider === "ollama")).toMatchObject({
      connected: true,
      modelCount: 1,
    });
  });

  it("marks ollama disconnected when listModels throws", async () => {
    const statuses = await getProviderStatuses({
      apiKeyStore: new MemoryApiKeyStore(),
      providers: {
        ollama: {
          name: "ollama",
          stream: vi.fn(),
          listModels: vi.fn().mockRejectedValue(new Error("ECONNREFUSED")),
        },
      },
    });
    expect(statuses.find((s) => s.provider === "ollama")).toMatchObject({
      connected: false,
      reason: "ECONNREFUSED",
    });
  });
});
