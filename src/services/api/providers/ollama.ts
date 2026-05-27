import type { Message as OllamaMessage } from "ollama";
import { Ollama } from "ollama";
import { toOpenAIFunction } from "../toolSchema";
import type { CallModelParams, Provider, ProviderEvent } from "../types";

export class OllamaProvider implements Provider {
  readonly name = "ollama";
  constructor(private env: NodeJS.ProcessEnv) {}

  async *stream(params: CallModelParams): AsyncGenerator<ProviderEvent> {
    const host = this.env.OLLAMA_HOST ?? "http://localhost:11434";
    const model = params.model ?? this.env.OLLAMA_MODEL ?? "qwen2.5:14b";
    const client = new Ollama({ host });
    const toolDefs = params.tools.map((t) => {
      const fn = toOpenAIFunction(t);
      return { type: "function" as const, function: fn.function };
    });
    const toolUseToName = new Map<string, string>();
    for (const m of params.messages) {
      if (m.role === "assistant") {
        for (const b of m.content) {
          if (b.type === "tool_use") toolUseToName.set(b.id, b.name);
        }
      }
    }
    const messages: OllamaMessage[] = [
      { role: "system", content: params.system },
      ...params.messages.map((m): OllamaMessage => {
        if (m.role === "user") return { role: "user", content: m.content };
        if (m.role === "assistant") {
          const textParts = m.content
            .filter((b): b is { type: "text"; text: string } => b.type === "text")
            .map((b) => b.text)
            .join("");
          const toolCalls = m.content
            .filter(
              (b): b is { type: "tool_use"; id: string; name: string; input: unknown } =>
                b.type === "tool_use",
            )
            .map((b) => ({
              function: { name: b.name, arguments: b.input as Record<string, unknown> },
            }));
          return {
            role: "assistant" as const,
            content: textParts,
            ...(toolCalls.length ? { tool_calls: toolCalls } : {}),
          };
        }
        return {
          role: "tool" as const,
          name: toolUseToName.get(m.toolUseId) ?? m.toolUseId,
          content: m.content,
        } as OllamaMessage;
      }),
    ];
    try {
      const stream = await client.chat({
        model,
        messages,
        stream: true,
        ...(toolDefs.length ? { tools: toolDefs } : {}),
      });
      let outputTokens = 0;
      let toolCallIdx = 0;
      for await (const part of stream) {
        if (part.message?.content) yield { type: "text_delta", text: part.message.content };
        const calls = (
          part.message as {
            tool_calls?: Array<{ function: { name: string; arguments: unknown } }>;
          }
        ).tool_calls;
        if (calls) {
          for (const c of calls) {
            const id = `ollama-${toolCallIdx++}`;
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
