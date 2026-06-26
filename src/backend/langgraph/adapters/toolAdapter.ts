import type { Tool, ToolProgress } from "src/Tool";
import type { LoopContext } from "src/loopContext";

export interface ToolRun {
  progress: ToolProgress[];
  output: unknown;
  isError: boolean;
}

export async function runTool(tool: Tool, input: unknown, ctx: LoopContext): Promise<ToolRun> {
  const progress: ToolProgress[] = [];
  // `input` is already validated by the caller (toolsNode).
  const gen = tool.call(input, ctx);
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
