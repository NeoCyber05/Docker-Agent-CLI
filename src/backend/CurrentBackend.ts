import type { AgentBackend, BackendQueryParams } from "./AgentBackend";
import type { LoopEvent } from "src/types/events";

export class CurrentBackend implements AgentBackend {
  readonly name = "current" as const;

  async *query(params: BackendQueryParams): AsyncGenerator<LoopEvent, void> {
    // Body filled in Task 1.2.
    void params;
    yield { type: "error", error: new Error("CurrentBackend not wired") };
  }
}
