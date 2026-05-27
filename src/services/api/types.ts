import type { Message } from "src/types/message";

export interface UsageInfo {
  inputTokens: number;
  outputTokens: number;
}

export type ProviderEvent =
  | { type: "text_delta"; text: string }
  | { type: "tool_use_start"; id: string; name: string }
  | { type: "tool_use_delta"; id: string; argsPartialJson: string }
  | { type: "tool_use_stop"; id: string }
  | {
      type: "message_stop";
      stopReason: "end_turn" | "tool_use" | "max_tokens";
    }
  | ({ type: "usage" } & UsageInfo)
  | { type: "error"; error: Error };

export interface ToolSchema {
  name: string;
  description: string;
  inputSchema: import("zod").ZodSchema<unknown>;
}

export interface CallModelParams {
  messages: Message[];
  tools: ToolSchema[];
  system: string;
  model?: string;
}

export interface Provider {
  stream(params: CallModelParams): AsyncGenerator<ProviderEvent>;
}
