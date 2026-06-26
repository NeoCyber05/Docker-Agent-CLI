import { query } from "src/query";
import type { LoopEvent } from "src/types/events";
import type { AgentBackend, BackendQueryParams } from "./AgentBackend";

export class CurrentBackend implements AgentBackend {
  readonly name = "current" as const;

  async *query(params: BackendQueryParams): AsyncGenerator<LoopEvent, void> {
    yield* query(params);
  }
}
