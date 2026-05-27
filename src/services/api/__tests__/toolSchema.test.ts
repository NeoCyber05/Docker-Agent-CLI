import {
  toGeminiFunctionDeclaration,
  toJsonSchema,
  toOpenAIFunction,
} from "src/services/api/toolSchema";
import { describe, expect, test } from "vitest";
import { z } from "zod";

describe("toolSchema", () => {
  const schema = z.object({
    name: z.string(),
    count: z.number().int().min(1).optional(),
  });

  test("toJsonSchema produces JSON Schema with required fields", () => {
    const js = toJsonSchema(schema);
    expect(js).toMatchObject({
      type: "object",
      properties: { name: { type: "string" }, count: { type: "integer" } },
      required: ["name"],
    });
  });

  test("toGeminiFunctionDeclaration wraps with name + description", () => {
    const decl = toGeminiFunctionDeclaration({
      name: "demo",
      description: "do thing",
      inputSchema: schema,
    });
    expect(decl.name).toBe("demo");
    expect(decl.parameters).toMatchObject({ type: "object" });
  });

  test("toOpenAIFunction wraps with .function.parameters", () => {
    const fn = toOpenAIFunction({
      name: "demo",
      description: "do thing",
      inputSchema: schema,
    });
    expect(fn).toMatchObject({
      type: "function",
      function: { name: "demo", description: "do thing" },
    });
  });
});
