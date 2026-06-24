import * as fs from "node:fs";
import { stackStateYamlPath } from "src/config";
import type { Tool, ToolProgress } from "src/Tool";
import type { ComposePsRow } from "src/services/docker/composeRunner";
import { scrubLine } from "src/state/secretRedactor";
import { z } from "zod";
import { collectSecretKeys } from "./shared/secretKeys";

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
    const yamlPath = stackStateYamlPath(ctx.cwd, input.stackName);
    if (!fs.existsSync(yamlPath)) {
      return { rows: [], logTail: `stack ${input.stackName} not found` };
    }

    yield { type: "progress", msg: `Compose ps + logs for ${input.stackName}...` };
    const secretKeys = collectSecretKeys(input.stackName, ctx);
    const bound = ctx.composeRunner.forStack(input.stackName, yamlPath);
    const rows = await bound.ps({ json: true });
    const logs = bound.logs({ tailLines: input.tailLines ?? 50 });
    let logTail = "";

    while (true) {
      const r = await logs.next();
      if (r.done) break;
      logTail += scrubLine(r.value, secretKeys);
    }

    return { rows, logTail };
  },
};
