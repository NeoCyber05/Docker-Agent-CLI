import { query } from "src/query";
import type { AgentBackend, BackendQueryParams } from "./AgentBackend";

export class CurrentBackend implements AgentBackend {
  readonly name = "current" as const;

  async *query(params: BackendQueryParams) {
    yield* query(params);
  }
}
