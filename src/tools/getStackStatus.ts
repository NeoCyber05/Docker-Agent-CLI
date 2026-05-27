import * as fs from "node:fs";
import * as path from "node:path";
import type { Tool, ToolProgress } from "src/Tool";
import type { ComposePsRow } from "src/services/docker/composeRunner";
import { z } from "zod";

export const GetStackStatusInputSchema = z.object({
  stackName: z.string(),
  tailLines: z.number().int().min(0).max(1000).optional(),
});

export type GetStackStatusInput = z.infer<typeof GetStackStatusInputSchema>;

export interface GetStackStatusResult {
  rows: ComposePsRow[];
  logTail: string;
}

export const getStackStatus: Tool<GetStackStatusInput, GetStackStatusResult> = {
  name: "get_stack_status",
  description: "Show container state, health, ports, and last log lines for a stack.",
  inputSchema: GetStackStatusInputSchema,
  category: "read-only",
  needsPermission: () => false,
  call: async function* (input, ctx): AsyncGenerator<ToolProgress, GetStackStatusResult> {
    const yamlPath = path.join(ctx.cwd, ".docker-agent", "stacks", `${input.stackName}.yaml`);
    if (!fs.existsSync(yamlPath)) {
      return { rows: [], logTail: `stack ${input.stackName} not found` };
    }

    yield { type: "progress", msg: `Compose ps + logs for ${input.stackName}...` };
    const bound = ctx.composeRunner.forStack(input.stackName, yamlPath);
    const rows = await bound.ps({ json: true });
    const logs = bound.logs({ tailLines: input.tailLines ?? 50 });
    let logTail = "";

    while (true) {
      const r = await logs.next();
      if (r.done) break;
      logTail += r.value;
    }

    return { rows, logTail };
  },
};
