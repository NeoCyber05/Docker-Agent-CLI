import type { ComposeRunner } from "src/services/docker/composeRunner";
import type { EngineClient } from "src/services/docker/engineClient";
import type { ImageValidator } from "src/services/docker/imageValidator";
import type { StateStore } from "src/state/StateStore";
import type { z } from "zod";

export interface ToolContext {
  cwd: string;
  stateStore: StateStore;
  dockerEngine: EngineClient;
  composeRunner: ComposeRunner;
  abortSignal: AbortSignal;
  imageValidator?: ImageValidator;
}

export interface ToolProgress {
  type: "progress";
  msg: string;
}

export interface Tool<TInput = unknown, TOutput = unknown> {
  name: string;
  description: string;
  inputSchema: z.ZodSchema<TInput>;
  category: "high-level" | "escape-hatch" | "read-only";
  needsPermission: (input: TInput) => boolean;
  call(input: TInput, ctx: ToolContext): AsyncGenerator<ToolProgress, TOutput>;
}

export function findToolByName(tools: Tool[], name: string): Tool | undefined {
  return tools.find((t) => t.name === name);
}
