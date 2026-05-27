import type { Tool, ToolProgress } from "src/Tool";
import { z } from "zod";
import { destroyStack } from "./destroyStack";

export const DestroyAllStacksInputSchema = z.object({
  removeVolumes: z.boolean().optional(),
});

export type DestroyAllStacksInput = z.infer<typeof DestroyAllStacksInputSchema>;

export interface DestroyAllStacksResult {
  destroyed: string[];
  failed: Array<{ stack: string; exitCode: number }>;
}

export const destroyAllStacks: Tool<DestroyAllStacksInput, DestroyAllStacksResult> = {
  name: "destroy_all_stacks",
  description:
    "Tear down ALL stacks. Requires typed DESTROY ALL confirmation handled by L3 before invocation.",
  inputSchema: DestroyAllStacksInputSchema,
  category: "high-level",
  needsPermission: () => true,
  call: async function* (input, ctx): AsyncGenerator<ToolProgress, DestroyAllStacksResult> {
    const stacks = ctx.stateStore.list();
    const destroyed: string[] = [];
    const failed: Array<{ stack: string; exitCode: number }> = [];

    for (const stack of stacks) {
      yield { type: "progress", msg: `Destroying ${stack.name}...` };
      const gen = destroyStack.call(
        {
          stackName: stack.name,
          ...(input.removeVolumes ? { removeVolumes: true } : {}),
        },
        ctx,
      );

      let outcome = { ok: false, exitCode: -1 };
      try {
        while (true) {
          const r = await gen.next();
          if (r.done) {
            outcome = r.value;
            break;
          }
          yield r.value;
        }
      } catch (error) {
        yield {
          type: "progress",
          msg: `Failed to destroy ${stack.name}: ${error instanceof Error ? error.message : String(error)}`,
        };
      }

      if (outcome.ok) {
        destroyed.push(stack.name);
      } else {
        failed.push({ stack: stack.name, exitCode: outcome.exitCode });
      }
    }

    return { destroyed, failed };
  },
};
