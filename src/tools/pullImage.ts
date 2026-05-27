import type { Tool, ToolProgress } from "src/Tool";
import { z } from "zod";

export const PullImageInputSchema = z.object({ image: z.string() });
export type PullImageInput = z.infer<typeof PullImageInputSchema>;

export interface PullImageResult {
  ok: boolean;
}

export const pullImage: Tool<PullImageInput, PullImageResult> = {
  name: "pull_image",
  description:
    "Placeholder for future Docker image pre-pull support; currently validates intent only.",
  inputSchema: PullImageInputSchema,
  category: "escape-hatch",
  needsPermission: () => true,
  call: async function* (input): AsyncGenerator<ToolProgress, PullImageResult> {
    yield { type: "progress", msg: `Pulling ${input.image}...` };
    return { ok: true };
  },
};
