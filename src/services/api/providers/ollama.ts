import { Ollama } from "ollama";
import { toOpenAIFunction } from "../toolSchema";
import type { CallModelParams, Provider, ProviderEvent } from "../types";
import type { ToolSchema } from "../types";

export class OllamaProvider implements Provider {
  readonly name = "ollama";
  constructor(private env: NodeJS.ProcessEnv) {}

  async *stream(params: CallModelParams): AsyncGenerator<ProviderEvent> {
    const host = this.env.OLLAMA_HOST ?? "http://localhost:11434";
    const model = params.model ?? this.env.OLLAMA_MODEL ?? "qwen2.5:14b";
    const client = new Ollama({ host });
    const tools = (params.tools as ToolSchema[]).map((t) => {
      const fn = toOpenAIFunction(t as never);
      return { type: "function" as const, function: fn.function };
    });
    const messages = [
      { role: "system", content: params.system },
      ...params.messages.map((m) => {
        if (m.role === "user") return { role: "user", content: m.content };
        if (m.role === "assistant") {
          return {
            role: "assistant",
            content: m.content
              .filter((b): b is { type: "text"; text: string } => b.type === "text")
              .map((b) => b.text)
              .join(""),
          };
        }
        return { role: "tool", content: m.content };
      }),
    ];
    try {
      const stream = await client.chat({
        model,
        messages,
        stream: true,
        ...(tools.length ? { tools } : {}),
      });
      let outputTokens = 0;
      for await (const part of stream) {
        if (part.message?.content) yield { type: "text_delta", text: part.message.content };
        const calls = (
          part.message as {
            tool_calls?: Array<{ function: { name: string; arguments: unknown } }>;
          }
        ).tool_calls;
        if (calls) {
          for (const c of calls) {
            const id = `ollama-${Math.random().toString(36).slice(2, 8)}`;
            yield { type: "tool_use_start", id, name: c.function.name };
            yield {
              type: "tool_use_delta",
              id,
              argsPartialJson: JSON.stringify(c.function.arguments),
            };
            yield { type: "tool_use_stop", id };
          }
        }
        if (part.eval_count) outputTokens = part.eval_count;
      }
      yield { type: "usage", inputTokens: 0, outputTokens };
      yield { type: "message_stop", stopReason: "end_turn" };
    } catch (err) {
      yield { type: "error", error: err as Error };
    }
  }
}
