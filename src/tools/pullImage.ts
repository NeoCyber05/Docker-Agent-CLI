import type { Tool, ToolProgress } from "src/Tool";
import { createImageValidator } from "src/services/docker/imageValidator";
import { z } from "zod";

export const PullImageInputSchema = z.object({ image: z.string() });
export type PullImageInput = z.infer<typeof PullImageInputSchema>;

export interface PullImageResult {
  ok: boolean;
  status: "valid" | "invalid" | "unknown";
  source?: "local" | "registry" | "pulled" | "unavailable";
  error?: string;
  suggestion?: string;
}

export const pullImage: Tool<PullImageInput, PullImageResult> = {
  name: "pull_image",
  description:
    "Validate a Docker image reference and pre-pull it when it exists in a registry but is not local.",
  inputSchema: PullImageInputSchema,
  category: "escape-hatch",
  needsPermission: () => true,
  call: async function* (input, ctx): AsyncGenerator<ToolProgress, PullImageResult> {
    const validator = ctx.imageValidator ?? createImageValidator(ctx.dockerEngine);
    yield { type: "progress", msg: `Validating ${input.image}...` };
    const validation = await validator.validateImage(input.image, { signal: ctx.abortSignal });

    if (validation.status === "invalid") {
      return {
        ok: false,
        status: "invalid",
        source: validation.source,
        ...(validation.error ? { error: validation.error } : {}),
        ...(validation.suggestion ? { suggestion: validation.suggestion } : {}),
      };
    }

    if (validation.status === "unknown") {
      return {
        ok: true,
        status: "unknown",
        source: validation.source,
        ...(validation.error ? { error: validation.error } : {}),
      };
    }

    if (validation.source === "registry") {
      if (!ctx.dockerEngine.pullImage) {
        return {
          ok: false,
          status: "valid",
          source: "registry",
          error: "Docker engine does not support image pulling",
        };
      }
      yield { type: "progress", msg: `Pulling ${input.image}...` };
      for await (const line of ctx.dockerEngine.pullImage(input.image, {
        signal: ctx.abortSignal,
      })) {
        yield { type: "progress", msg: line };
      }
      return { ok: true, status: "valid", source: "pulled" };
    }

    return { ok: true, status: "valid", source: validation.source };
  },
};
