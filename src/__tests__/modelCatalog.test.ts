import { type CatalogEntry, buildModelCatalog, flattenCatalog } from "src/services/modelCatalog";
import type { ProviderStatus } from "src/services/providerStatus";
import { describe, expect, it, vi } from "vitest";

const STATUSES: ProviderStatus[] = [
  { provider: "openai", connected: true },
  { provider: "gemini", connected: false, reason: "API key not set" },
  { provider: "ollama", connected: false, reason: "ECONNREFUSED" },
  { provider: "openrouter", connected: false, reason: "API key not set" },
];

describe("buildModelCatalog", () => {
  it("loads models only for connected providers", async () => {
    const catalog = await buildModelCatalog(STATUSES, {
      openai: {
        name: "openai",
        stream: vi.fn(),
        listModels: vi.fn().mockResolvedValue(["gpt-4o-mini"]),
      },
      gemini: { name: "gemini", stream: vi.fn(), listModels: vi.fn() },
      ollama: { name: "ollama", stream: vi.fn(), listModels: vi.fn() },
      openrouter: { name: "openrouter", stream: vi.fn(), listModels: vi.fn() },
    });
    expect(catalog).toEqual([
      { provider: "gemini", connected: false, reason: "API key not set" },
      { provider: "openai", connected: true, models: ["gpt-4o-mini"] },
      { provider: "ollama", connected: false, reason: "ECONNREFUSED" },
      { provider: "openrouter", connected: false, reason: "API key not set" },
    ]);
  });
});

describe("flattenCatalog", () => {
  it("emits connect rows for disconnected providers", () => {
    const catalog: CatalogEntry[] = [
      { provider: "openai", connected: true, models: ["gpt-4o-mini"] },
      { provider: "gemini", connected: false, reason: "API key not set" },
    ];
    const rows = flattenCatalog(catalog);
    expect(rows).toContainEqual({ kind: "connect", provider: "gemini", reason: "API key not set" });
    expect(rows).toContainEqual({ kind: "model", provider: "openai", model: "gpt-4o-mini" });
  });
});
