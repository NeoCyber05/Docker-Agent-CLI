import type { Tool, ToolProgress, ToolContext } from "src/Tool";
import type { ServiceSpec } from "src/types/stack";
import { z } from "zod";
import { detectMissingConfigFiles, stageConfigFiles } from "./shared/configFiles";
import { validateImagesForTool } from "./shared/imageValidation";
import { ServicesSchema, type StackDraft } from "./shared/specSchemas";
import { prepareStackDraft } from "./shared/translator";

export const ValidateSpecInputSchema = z.object({
  stackName: z
    .string()
    .regex(/^[a-z][a-z0-9_-]{0,62}$/)
    .optional(),
  intent: z.string().optional(),
  services: ServicesSchema,
  configFiles: z.record(z.string()).optional(),
});

export type ValidateSpecInput = z.infer<typeof ValidateSpecInputSchema>;

export interface SpecIssue {
  code: "invalid_image" | "invalid_config_path" | "missing_config_file" | "invalid_spec";
  path: string;
  message: string;
}

export interface ValidateSpecResult {
  valid: boolean;
  issues: SpecIssue[];
  warnings: string[];
}

export async function validateSpecInput(
  input: { services: Record<string, ServiceSpec>; configFiles?: Record<string, string> },
  ctx: ToolContext,
): Promise<ValidateSpecResult> {
  const issues: SpecIssue[] = [];
  const imageValidation = await validateImagesForTool(
    Object.values(input.services).map((service) => service.image),
    ctx,
  );
  if (imageValidation.error) {
    issues.push({ code: "invalid_image", path: "services", message: imageValidation.error });
  }

  const staged = stageConfigFiles(
    ctx.cwd,
    input.services,
    input.configFiles,
  );
  if (!staged.ok) {
    issues.push({ code: "invalid_config_path", path: "configFiles", message: staged.error });
  } else {
    const missing = detectMissingConfigFiles(
      input.services,
      new Set(staged.staged.map((file) => file.path)),
      ctx.cwd,
    );
    for (const item of missing) {
      issues.push({
        code: "missing_config_file",
        path: `services.${item.service}.volumes`,
        message: `Missing content for bind-mounted config file '${item.path}'.`,
      });
    }
  }

  return { valid: issues.length === 0, issues, warnings: imageValidation.warnings };
}

export const validateSpec: Tool<ValidateSpecInput, ValidateSpecResult> = {
  name: "validate_spec",
  description:
    "Validate a draft stack service spec: Docker images, bind-mounted config paths, and missing config file content.",
  inputSchema: ValidateSpecInputSchema,
  category: "read-only",
  needsPermission: () => false,
  call: async function* (input, ctx): AsyncGenerator<ToolProgress, ValidateSpecResult> {
    yield { type: "progress", msg: "Validating stack spec..." };
    const draft: StackDraft = {
      stackName: input.stackName ?? "validate-temp-stack",
      intent: input.intent ?? "validation only",
      services: input.services,
      configFiles: input.configFiles,
    };
    const prep = await prepareStackDraft(draft, ctx);
    if (!prep.ok) {
      return {
        valid: false,
        issues: (prep.issues as SpecIssue[]) ?? [
          { code: "invalid_spec", path: "services", message: prep.error },
        ],
        warnings: [],
      };
    }
    const specInput: any = {
      services: prep.prepared.services,
    };
    if (input.configFiles !== undefined) {
      specInput.configFiles = input.configFiles;
    }
    return validateSpecInput(specInput, ctx);
  },
};
