import type { Tool, ToolProgress } from "src/Tool";
import type { ServiceSpec } from "src/types/stack";
import { z } from "zod";
import { detectMissingConfigFiles, stageConfigFiles } from "./shared/configFiles";
import { validateImagesForTool } from "./shared/imageValidation";
import { ServicesSchema } from "./shared/specSchemas";

export const ValidateSpecInputSchema = z.object({
  services: ServicesSchema,
  configFiles: z.record(z.string()).optional(),
});

export type ValidateSpecInput = z.infer<typeof ValidateSpecInputSchema>;

export interface SpecIssue {
  code: "invalid_image" | "invalid_config_path" | "missing_config_file";
  path: string;
  message: string;
}

export interface ValidateSpecResult {
  valid: boolean;
  issues: SpecIssue[];
  warnings: string[];
}

export async function validateSpecInput(
  input: ValidateSpecInput,
  ctx: import("src/Tool").ToolContext,
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
    input.services as Record<string, ServiceSpec>,
    input.configFiles,
  );
  if (!staged.ok) {
    issues.push({ code: "invalid_config_path", path: "configFiles", message: staged.error });
  } else {
    const missing = detectMissingConfigFiles(
      input.services as Record<string, ServiceSpec>,
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
    return validateSpecInput(input, ctx);
  },
};
