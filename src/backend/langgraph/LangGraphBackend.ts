import type { LoopEvent } from "src/types/events";
import { AsyncQueue } from "src/utils/AsyncQueue";
import type { AgentBackend, BackendQueryParams } from "../AgentBackend";
import type { AgentState } from "./state";

export class LangGraphBackend implements AgentBackend {
  readonly name = "langgraph" as const;

  async *query(params: BackendQueryParams): AsyncGenerator<LoopEvent, void> {
    const queue = new AsyncQueue<LoopEvent>();
    const emit = (ev: LoopEvent) => queue.push(ev);

    const runner = (async () => {
      try {
        const { buildGraph } = await import("./graph");
        const graph = buildGraph({
          provider: params.provider,
          ctx: params.ctx,
          ...(params.model !== undefined ? { model: params.model } : {}),
          emit,
        });
        const initialState: typeof AgentState.State = {
          messages: params.messages,
          iter: 0,
          allowSet: params.ctx.allowSet,
          pendingToolResults: [],
          progress: [],
          pendingApproval: null,
        };
        const stream = await graph.stream(initialState, {
          streamMode: "values",
          recursionLimit: 50,
          signal: params.ctx.abortSignal,
        });
        for await (const _state of stream) {
          if (params.ctx.abortSignal.aborted) break;
          // Events are already emitted by node callbacks via `emit`.
        }
      } catch (err) {
        if (!params.ctx.abortSignal.aborted) {
          queue.push({ type: "error", error: err as Error });
        }
      } finally {
        queue.close();
      }
    })();

    for await (const ev of queue) yield ev;
    await runner;
  }
}
