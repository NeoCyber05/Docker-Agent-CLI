import type { Tool, ToolProgress } from "src/Tool";
import { detectDrift } from "src/state/driftDetector";
import type { StackDiff } from "src/types/stack";
import { z } from "zod";

export const InspectDriftInputSchema = z.object({ stackName: z.string() });
export type InspectDriftInput = z.infer<typeof InspectDriftInputSchema>;

export const inspectDrift: Tool<InspectDriftInput, StackDiff> = {
  name: "inspect_drift",
  description: "Compare desired state (stack YAML) with actual state (live containers).",
  inputSchema: InspectDriftInputSchema,
  category: "read-only",
  needsPermission: () => false,
  call: async function* (input, ctx): AsyncGenerator<ToolProgress, StackDiff> {
    yield { type: "progress", msg: `Inspecting drift for ${input.stackName}...` };
    return await detectDrift(input.stackName, ctx.stateStore, ctx.dockerEngine, ctx.cwd);
  },
};
