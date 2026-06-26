import type { Tool, ToolProgress } from "src/Tool";
import type { LoopContext } from "src/loopContext";

export interface ToolRun {
  progress: ToolProgress[];
  output: unknown;
  isError: boolean;
}

export async function runTool(
  tool: Tool,
  input: unknown,
  ctx: LoopContext,
): Promise<ToolRun> {
  const progress: ToolProgress[] = [];
  let parsed: unknown = input;
  try {
    parsed = tool.inputSchema.parse(input);
  } catch (err) {
    return {
      progress: [{ type: "progress", msg: `validation failed: ${(err as Error).message}` }],
      output: `validation failed: ${(err as Error).message}`,
      isError: true,
    };
  }
  const gen = tool.call(parsed, ctx);
  let output: unknown;
  while (true) {
    const r = await gen.next();
    if (r.done) {
      output = r.value;
      break;
    }
    progress.push(r.value);
  }
  return { progress, output, isError: false };
}
