import * as fs from "node:fs";
import { stackStateYamlPath } from "src/config";
import type { Tool, ToolProgress } from "src/Tool";
import { z } from "zod";

export const DestroyStackInputSchema = z.object({
  stackName: z.string(),
  removeVolumes: z.boolean().optional(),
});

export type DestroyStackInput = z.infer<typeof DestroyStackInputSchema>;

export interface DestroyStackResult {
  ok: boolean;
  exitCode: number;
}

export const destroyStack: Tool<DestroyStackInput, DestroyStackResult> = {
  name: "destroy_stack",
  description:
    "Tear down a stack via Compose down (optionally with volumes) and archive its state.",
  inputSchema: DestroyStackInputSchema,
  category: "high-level",
  needsPermission: () => true,
  call: async function* (input, ctx): AsyncGenerator<ToolProgress, DestroyStackResult> {
    const yamlPath = stackStateYamlPath(ctx.cwd, input.stackName);
    if (!fs.existsSync(yamlPath)) {
      yield { type: "progress", msg: `No stack file for ${input.stackName}; nothing to do.` };
      return { ok: true, exitCode: 0 };
    }

    yield { type: "progress", msg: `Compose down for ${input.stackName}...` };
    const bound = ctx.composeRunner.forStack(input.stackName, yamlPath);
    const gen = bound.down(input.removeVolumes ? { volumes: true } : {});

    while (true) {
      const r = await gen.next();
      if (r.done) {
        ctx.stateStore.remove(input.stackName);
        ctx.stateStore.appendHistory({
          ts: new Date().toISOString(),
          sessionId: "unknown",
          stackName: input.stackName,
          action: "destroy",
          details: { removeVolumes: input.removeVolumes ?? false, exitCode: r.value },
        });
        return { ok: r.value === 0, exitCode: r.value };
      }
      yield { type: "progress", msg: r.value.trimEnd() };
    }
  },
};
