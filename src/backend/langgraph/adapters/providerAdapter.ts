import type { LoopContext } from "src/loopContext";
import type { Provider, ProviderEvent } from "src/services/api/types";
import type { Message } from "src/types/message";
import { getAgentTools } from "src/tools";
import { buildSystemPrompt } from "src/context";

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
    switch ((ev as ProviderEvent).type) {
      case "text_delta":
        text += (ev as { text: string }).text;
        params.onEvent({ type: "assistant_text", text: (ev as { text: string }).text });
        break;
      case "tool_use_start":
        toolUses.push({ id: (ev as { id: string; name: string }).id, name: (ev as { id: string; name: string }).name, argsPartial: "" });
        break;
      case "tool_use_delta": {
        const d = ev as { id: string; argsPartialJson: string };
        const u = toolUses.find((t) => t.id === d.id);
        if (u) u.argsPartial += d.argsPartialJson;
        break;
      }
      case "tool_use_stop":
        break;
      case "message_stop":
        stopReason = (ev as { stopReason: ProviderTurn["stopReason"] }).stopReason;
        break;
      case "usage":
        usage = { inputTokens: (ev as { inputTokens: number }).inputTokens, outputTokens: (ev as { outputTokens: number }).outputTokens };
        params.onEvent({ type: "usage", ...usage });
        break;
      case "error": {
        const err = (ev as { error: Error }).error;
        params.onEvent({ type: "error", error: err });
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
