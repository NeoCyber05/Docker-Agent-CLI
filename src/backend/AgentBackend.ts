import type { LoopContext } from "src/loopContext";
import type { Provider } from "src/services/api/types";
import type { LoopEvent } from "src/types/events";
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

export async function createBackend(): Promise<AgentBackend> {
  const flag = process.env.DOCKER_AGENT_BACKEND ?? "current";
  if (flag === "langgraph") {
    const { LangGraphBackend } = await import("./langgraph/LangGraphBackend");
    return new LangGraphBackend();
  }
  return new CurrentBackend();
}
