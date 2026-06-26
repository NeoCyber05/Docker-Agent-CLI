import { buildSystemPrompt } from "src/context";
import type { LoopContext } from "src/loopContext";
import type { Provider, ProviderEvent } from "src/services/api/types";
import { getAgentTools } from "src/tools";
import type { Message } from "src/types/message";

export interface ProviderTurn {
  text: string;
  toolUses: { id: string; name: string; argsPartial: string }[];
  stopReason: "end_turn" | "tool_use" | "max_tokens";
  usage?: { inputTokens: number; outputTokens: number };
}

export interface StreamedEvent {
  type: "assistant_text" | "usage" | "error";
  text?: string;
  inputTokens?: number;
  outputTokens?: number;
  error?: Error;
}

/**
 * Drive the existing Provider asynchronously, emitting streamed LoopEvent-equivalents
 * through `onEvent`, and returning the structured turn for the graph node.
 */
export async function driveProvider(params: {
  provider: Provider;
  messages: Message[];
  ctx: LoopContext;
  model?: string;
  onEvent: (e: StreamedEvent) => void;
  signal: AbortSignal;
}): Promise<ProviderTurn> {
  const tools = getAgentTools();
  const system = buildSystemPrompt(params.ctx.stateStore.summary());
  const events = params.provider.stream({
    messages: params.messages,
    tools: tools.map((t) => ({
      name: t.name,
      description: t.description,
      inputSchema: t.inputSchema,
    })),
    system,
    ...(params.model ? { model: params.model } : {}),
    signal: params.signal,
  });

  let text = "";
  const toolUses: { id: string; name: string; argsPartial: string }[] = [];
  let stopReason: ProviderTurn["stopReason"] = "end_turn";
  let usage: { inputTokens: number; outputTokens: number } | undefined;

  for await (const ev of events) {
    if (params.signal.aborted) {
      const turn: ProviderTurn = { text, toolUses, stopReason: "end_turn" };
      if (usage !== undefined) turn.usage = usage;
      return turn;
    }
    switch (ev.type) {
      case "text_delta":
        text += ev.text;
        params.onEvent({ type: "assistant_text", text: ev.text });
        break;
      case "tool_use_start":
        toolUses.push({
          id: ev.id,
          name: ev.name,
          argsPartial: "",
        });
        break;
      case "tool_use_delta": {
        const u = toolUses.find((t) => t.id === ev.id);
        if (u) u.argsPartial += ev.argsPartialJson;
        break;
      }
      case "tool_use_stop":
        break;
      case "message_stop":
        stopReason = ev.stopReason;
        break;
      case "usage":
        usage = {
          inputTokens: ev.inputTokens,
          outputTokens: ev.outputTokens,
        };
        params.onEvent({ type: "usage", ...usage });
        break;
      case "error": {
        params.onEvent({ type: "error", error: ev.error });
        const turn: ProviderTurn = { text, toolUses, stopReason: "end_turn" };
        if (usage !== undefined) turn.usage = usage;
        return turn;
      }
    }
  }
  const turn: ProviderTurn = { text, toolUses, stopReason };
  if (usage !== undefined) turn.usage = usage;
  return turn;
}
