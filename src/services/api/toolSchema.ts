import type { z } from "zod";

export interface ToolSchemaInput {
  name: string;
  description: string;
  inputSchema: z.ZodSchema<unknown>;
}

type JsonSchemaType = "string" | "number" | "integer" | "boolean" | "object" | "array";

interface JsonSchemaObject {
  type: "object";
  properties: Record<string, JsonSchemaNode>;
  required: string[];
  additionalProperties?: boolean;
}

interface JsonSchemaNode {
  type?: JsonSchemaType;
  description?: string;
  items?: JsonSchemaNode;
  properties?: Record<string, JsonSchemaNode>;
  required?: string[];
  additionalProperties?: boolean;
  enum?: unknown[];
  oneOf?: JsonSchemaNode[];
}

export function toJsonSchema(schema: z.ZodTypeAny): JsonSchemaNode {
  const def = (schema as unknown as Record<string, unknown>)._def as { typeName: string };
  switch (def.typeName) {
    case "ZodString":
      return { type: "string" };
    case "ZodNumber": {
      const checks = (def as unknown as { checks?: Array<{ kind: string }> }).checks ?? [];
      const isInt = checks.some((c) => c.kind === "int");
      return { type: isInt ? "integer" : "number" };
    }
    case "ZodBoolean":
      return { type: "boolean" };
    case "ZodArray":
      return {
        type: "array",
        items: toJsonSchema((def as unknown as { type: z.ZodTypeAny }).type),
      };
    case "ZodObject": {
      const shape = (def as unknown as { shape: () => Record<string, z.ZodTypeAny> }).shape();
      const properties: Record<string, JsonSchemaNode> = {};
      const required: string[] = [];
      for (const [key, value] of Object.entries(shape)) {
        const isOpt = (value as unknown as { isOptional?: () => boolean }).isOptional?.() ?? false;
        properties[key] = toJsonSchema(value);
        if (!isOpt) required.push(key);
      }
      return { type: "object", properties, required, additionalProperties: false };
    }
    case "ZodOptional":
      return toJsonSchema((def as unknown as { innerType: z.ZodTypeAny }).innerType);
    case "ZodEnum":
      return { type: "string", enum: (def as unknown as { values: string[] }).values };
    case "ZodUnion":
      return {
        oneOf: (def as unknown as { options: z.ZodTypeAny[] }).options.map(toJsonSchema),
      };
    case "ZodRecord":
      return { type: "object" };
    case "ZodEffects":
      return toJsonSchema((def as unknown as { schema: z.ZodTypeAny }).schema);
    default:
      return {};
  }
}

export function toGeminiFunctionDeclaration(t: ToolSchemaInput) {
  return {
    name: t.name,
    description: t.description,
    parameters: toJsonSchema(t.inputSchema) as JsonSchemaObject,
  };
}

export function toOpenAIFunction(t: ToolSchemaInput) {
  return {
    type: "function" as const,
    function: {
      name: t.name,
      description: t.description,
      parameters: toJsonSchema(t.inputSchema) as JsonSchemaObject,
    },
  };
}
