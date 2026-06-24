import { describe, expect, test } from "vitest";
import { composeYamlForPreview } from "../composeBuilder";

describe("composeYamlForPreview", () => {
  test("removes x-docker-agent metadata from compose YAML", () => {
    const yaml = [
      "x-docker-agent:",
      "  name: redis-cache",
      "  createdAt: 2026-06-23T06:11:12.361Z",
      "  lastApplied: 2026-06-23T06:13:01.634Z",
      '  intent: "Adjust redis-cache"',
      "  provider: unknown",
      "  generatedBy: unknown",
      "  envFileSources: {}",
      "services:",
      "  redis:",
      "    image: redis:7",
    ].join("\n");

    const preview = composeYamlForPreview(yaml);
    expect(preview).not.toContain("x-docker-agent");
    expect(preview).not.toContain("redis-cache");
    expect(preview).not.toContain("createdAt");
    expect(preview).toContain("services:");
    expect(preview).toContain("image: redis:7");
  });

  test("returns original YAML when parsing fails", () => {
    const malformed = "services: [unclosed";
    expect(composeYamlForPreview(malformed)).toBe(malformed);
  });
});