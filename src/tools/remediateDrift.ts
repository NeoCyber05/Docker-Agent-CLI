import type { Tool, ToolProgress } from "src/Tool";
import { detectDrift } from "src/state/driftDetector";
import type { StackDiff } from "src/types/stack";
import { stringify as stringifyYaml } from "yaml";
import { z } from "zod";

export const RemediateDriftInputSchema = z.object({
  stackName: z.string().min(1),
});
export type RemediateDriftInput = z.infer<typeof RemediateDriftInputSchema>;

export interface RemediateDriftResult {
  diff: StackDiff;
  desiredYaml: string; // serialized desired StackDefinition; empty string if no desired def
  remediable: boolean; // true when status is drift | missing | extra (and desired def exists)
  reason?: string; // why not remediable (e.g., "in_sync" or "no desired state")
}

export const remediateDrift: Tool<RemediateDriftInput, RemediateDriftResult> = {
  name: "remediate_drift",
  description:
    "Detect configuration drift for a stack and return the desired state for remediation. " +
    "The caller (L3) handles confirmation and re-apply.",
  inputSchema: RemediateDriftInputSchema,
  category: "high-level",
  needsPermission: () => true,
  call: async function* (input, ctx): AsyncGenerator<ToolProgress, RemediateDriftResult> {
    yield { type: "progress", msg: `Detecting drift for stack ${input.stackName}...` };
    const diff = await detectDrift(input.stackName, ctx.stateStore, ctx.dockerEngine, ctx.cwd);

    // in_sync: no-op
    if (diff.status === "in_sync") {
      return { diff, desiredYaml: "", remediable: false, reason: "in_sync" };
    }

    // Read the desired definition to serialize
    const def = ctx.stateStore.read(input.stackName);
    if (!def) {
      // no desired definition available (e.g. status="extra" with no recorded definition)
      return { diff, desiredYaml: "", remediable: false, reason: "no desired state" };
    }

    const desiredYaml = stringifyYaml(def);

    // remediable for drift, missing, extra (if def exists)
    return { diff, desiredYaml, remediable: true };
  },
};
