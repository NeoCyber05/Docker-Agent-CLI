import type { LoopContext } from "src/loopContext";
import type { Provider } from "src/services/api/types";
import type { LoopEvent } from "src/types/events";
import { driveProvider } from "../adapters/providerAdapter";
import type { AgentState } from "../state";

const MAX_ITERATIONS = 24;

export interface AgentNodeDeps {
  provider: Provider;
  model?: string;
  ctx: LoopContext;
  emit: (ev: LoopEvent) => void;
}

export const agentNode =
  ({ provider, model, ctx, emit }: AgentNodeDeps) =>
  async (state: typeof AgentState.State) => {
    if (state.iter >= MAX_ITERATIONS) {
      emit({
        type: "error",
        error: new Error(`agent loop reached max iterations (${MAX_ITERATIONS})`),
      });
      return { iter: state.iter };
    }
    emit({ type: "iteration_start", n: state.iter + 1 });
    const turn = await driveProvider({
      provider,
      messages: state.messages,
      ctx,
      ...(model !== undefined ? { model } : {}),
      signal: ctx.abortSignal,
      onEvent: (e) => {
        if (e.type === "assistant_text" && e.text) emit({ type: "assistant_text", delta: e.text });
        else if (e.type === "usage")
          emit({
            type: "usage",
            inputTokens: e.inputTokens as number,
            outputTokens: e.outputTokens as number,
          });
        else if (e.type === "error") emit({ type: "error", error: e.error as Error });
      },
    });
    const blocks: import("src/types/message").AssistantBlock[] = [];
    if (turn.text) blocks.push({ type: "text", text: turn.text });
    for (const tu of turn.toolUses) {
      let input: unknown = {};
      try {
        input = JSON.parse(tu.argsPartial || "{}");
      } catch {
        /* keep {} */
      }
      blocks.push({ type: "tool_use", id: tu.id, name: tu.name, input });
    }
    if (turn.stopReason === "max_tokens") {
      emit({ type: "error", error: new Error("provider response stopped: max tokens reached") });
    }
    return {
      messages: [{ role: "assistant", content: blocks }],
      iter: state.iter + 1,
    };
  };
