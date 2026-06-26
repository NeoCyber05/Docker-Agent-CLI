import type { LoopEvent } from "src/types/events";
import type { LoopContext } from "src/loopContext";
import type { Provider } from "src/services/api/types";
import type { Message } from "src/types/message";
import { CurrentBackend } from "./CurrentBackend";

export interface BackendQueryParams {
  messages: Message[];
  ctx: LoopContext;
  provider: Provider;
  model?: string;
}

export interface AgentBackend {
  readonly name: "current" | "langgraph";
  query(params: BackendQueryParams): AsyncGenerator<LoopEvent, void>;
}

export function createBackend(): AgentBackend {
  const flag = process.env.DOCKER_AGENT_BACKEND ?? "current";
  if (flag === "langgraph") {
    // Lazy import to keep startup fast when defaulting to current.
    // Implementation added in Phase 2.
    const { LangGraphBackend } = require("./langgraph/LangGraphBackend") as {
      LangGraphBackend: new () => AgentBackend;
    };
    return new LangGraphBackend();
  }
  return new CurrentBackend();
}
