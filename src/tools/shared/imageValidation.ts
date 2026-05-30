import type { ToolContext } from "src/Tool";
import {
  type ImageValidationResult,
  createImageValidator,
  formatImageValidationError,
  imageValidationWarnings,
} from "src/services/docker/imageValidator";

export interface ToolImageValidationResult {
  results: ImageValidationResult[];
  error: string | null;
  warnings: string[];
}

function shouldBlockUnknownImages(): boolean {
  return process.env.DOCKER_AGENT_IMAGE_VALIDATION_UNKNOWN === "block";
}

export async function validateImagesForTool(
  images: string[],
  ctx: ToolContext,
): Promise<ToolImageValidationResult> {
  const validator = ctx.imageValidator ?? createImageValidator(ctx.dockerEngine);
  const uniqueImages = [...new Set(images)];
  const results = await validator.validateImages(uniqueImages, { signal: ctx.abortSignal });
  return {
    results,
    error: formatImageValidationError(results, { blockUnknown: shouldBlockUnknownImages() }),
    warnings: imageValidationWarnings(results),
  };
}
