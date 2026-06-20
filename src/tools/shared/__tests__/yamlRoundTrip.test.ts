import type { StackDefinition } from "src/types/stack";
import { describe, expect, test } from "vitest";
import { stringify } from "yaml";
import { validateYamlRoundTrip } from "../yamlRoundTrip";

function validDef(): StackDefinition {
  return {
    "x-docker-agent": {
      name: "test",
      createdAt: "2026-01-01T00:00:00.000Z",
      lastApplied: null,
      intent: "test",
      provider: "gemini",
      generatedBy: "test",
      envFileSources: {},
    },
    services: {
      web: { image: "nginx:1.27-alpine", ports: ["8080:80"] },
    },
  };
}

describe("validateYamlRoundTrip", () => {
  test("passes for valid YAML round-trip", () => {
    const yaml = stringify(validDef());
    const result = validateYamlRoundTrip(yaml);
    expect(result.ok).toBe(true);
    expect(result.error).toBeUndefined();
  });

  test("fails for malformed YAML", () => {
    const result = validateYamlRoundTrip("services: [unclosed");
    expect(result.ok).toBe(false);
    expect(result.error).toContain("parse");
  });

  test("fails for valid YAML that does not match StackDefinition schema", () => {
    const result = validateYamlRoundTrip("foo: bar\n");
    expect(result.ok).toBe(false);
    expect(result.error).toContain("schema");
  });

  test("fails for empty string", () => {
    const result = validateYamlRoundTrip("");
    expect(result.ok).toBe(false);
  });
});
