import * as fs from "node:fs";
import { stackStateYamlPath } from "src/config";
import type { Tool, ToolProgress } from "src/Tool";
import { scrubLine } from "src/state/secretRedactor";
import { z } from "zod";
import { collectSecretKeys } from "./shared/secretKeys";

export const GetLogsInputSchema = z.object({
  stackName: z.string(),
  service: z.string().optional(),
  tailLines: z.number().int().min(0).max(1000).optional(),
  since: z.string().optional(),
});

export type GetLogsInput = z.infer<typeof GetLogsInputSchema>;

export interface GetLogsResult {
  logTail: string;
  lineCount: number;
  truncated: boolean;
  error?: string;
}

const MAX_BYTES = 16 * 1024;

/** Keep the newest lines so total UTF-8 size stays <= MAX_BYTES. */
function capNewest(lines: string[]): { text: string; truncated: boolean } {
  let total = 0;
  const kept: string[] = [];
  let truncated = false;
  // Walk newest-first so we keep the most recent lines, then restore order.
  for (let i = lines.length - 1; i >= 0; i--) {
    const size = Buffer.byteLength(lines[i] ?? "", "utf-8");
    if (total + size > MAX_BYTES) {
      truncated = true;
      break;
    }
    total += size;
    kept.push(lines[i] ?? "");
  }
  kept.reverse(); // restore chronological order regardless of truncation
  return { text: kept.join(""), truncated };
}

export const getLogs: Tool<GetLogsInput, GetLogsResult> = {
  name: "get_logs",
  description:
    "Fetch a bounded snapshot of a stack's logs for diagnosis (read-only, secrets redacted).",
  inputSchema: GetLogsInputSchema,
  category: "read-only",
  needsPermission: () => false,
  call: async function* (input, ctx): AsyncGenerator<ToolProgress, GetLogsResult> {
    const yamlPath = stackStateYamlPath(ctx.cwd, input.stackName);
    if (!fs.existsSync(yamlPath)) {
      return {
        logTail: `stack ${input.stackName} not found`,
        lineCount: 0,
        truncated: false,
      };
    }

    yield { type: "progress", msg: `Fetching logs for ${input.stackName}...` };

    // Collecting keys reads stack state, which can throw on partial/unparseable
    // state. Redaction must never block log retrieval: degrade to no known keys.
    let secretKeys: Set<string>;
    try {
      secretKeys = collectSecretKeys(input.stackName, ctx);
    } catch {
      secretKeys = new Set<string>();
    }
    const bound = ctx.composeRunner.forStack(input.stackName, yamlPath);

    try {
      const gen = bound.logs({
        tailLines: input.tailLines ?? 100,
        ...(input.service ? { service: input.service } : {}),
        ...(input.since ? { since: input.since } : {}),
      });

      const scrubbed: string[] = [];
      while (true) {
        const r = await gen.next();
        if (r.done) break;
        scrubbed.push(scrubLine(r.value, secretKeys));
      }

      const { text, truncated } = capNewest(scrubbed);
      // lineCount reflects total lines fetched (pre-cap), useful context for the agent.
      return { logTail: text, lineCount: scrubbed.length, truncated };
    } catch (e) {
      return {
        logTail: "",
        lineCount: 0,
        truncated: false,
        error: e instanceof Error ? e.message : String(e),
      };
    }
  },
};
