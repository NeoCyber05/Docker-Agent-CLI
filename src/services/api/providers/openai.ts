import OpenAI from "openai";
import { toOpenAIFunction } from "../toolSchema";
import type { CallModelParams, Provider, ProviderEvent } from "../types";
import type { ToolSchema } from "../types";

export class OpenAIProvider implements Provider {
  readonly name = "openai";
  constructor(private env: NodeJS.ProcessEnv) {}

  async *stream(params: CallModelParams): AsyncGenerator<ProviderEvent> {
    const apiKey = this.env.OPENAI_API_KEY;
    if (!apiKey) {
      yield { type: "error", error: new Error("OPENAI_API_KEY not set") };
      return;
    }
    const client = new OpenAI({
      apiKey,
      ...(this.env.OPENAI_BASE_URL ? { baseURL: this.env.OPENAI_BASE_URL } : {}),
    });
    const model = params.model ?? this.env.OPENAI_MODEL ?? "gpt-4o-mini";
    const toolDefs = (params.tools as ToolSchema[]).map((t) => toOpenAIFunction(t as never));

    const messages: OpenAI.ChatCompletionMessageParam[] = [
      { role: "system", content: params.system },
      ...params.messages.map((m): OpenAI.ChatCompletionMessageParam => {
        if (m.role === "user") return { role: "user", content: m.content };
        if (m.role === "assistant") {
          const text = m.content
            .filter((b): b is { type: "text"; text: string } => b.type === "text")
            .map((b) => b.text)
            .join("");
          const toolCalls = m.content
            .filter(
              (b): b is { type: "tool_use"; id: string; name: string; input: unknown } =>
                b.type === "tool_use",
            )
            .map((b) => ({
              id: b.id,
              type: "function" as const,
              function: { name: b.name, arguments: JSON.stringify(b.input) },
            }));
          return {
            role: "assistant",
            ...(text ? { content: text } : { content: null }),
            ...(toolCalls.length ? { tool_calls: toolCalls } : {}),
          };
        }
        return { role: "tool", tool_call_id: m.toolUseId, content: m.content };
      }),
    ];

    try {
      const stream = await client.chat.completions.create({
        model,
        messages,
        ...(toolDefs.length ? { tools: toolDefs as unknown as OpenAI.ChatCompletionTool[] } : {}),
        stream: true,
      });
      const toolBuffers = new Map<number, { id: string; name: string; args: string }>();
      let inputTokens = 0;
      let outputTokens = 0;
      let stopReason: "end_turn" | "tool_use" = "end_turn";
      for await (const chunk of stream) {
        const delta = chunk.choices[0]?.delta;
        if (!delta) continue;
        if (delta.content) yield { type: "text_delta", text: delta.content };
        for (const call of delta.tool_calls ?? []) {
          const idx = call.index;
          let buf = toolBuffers.get(idx);
          if (!buf) {
            buf = { id: call.id ?? `oa-${idx}`, name: call.function?.name ?? "", args: "" };
            toolBuffers.set(idx, buf);
            yield { type: "tool_use_start", id: buf.id, name: buf.name };
          }
          if (call.function?.arguments) {
            buf.args += call.function.arguments;
            yield {
              type: "tool_use_delta",
              id: buf.id,
              argsPartialJson: call.function.arguments,
            };
          }
        }
        const finish = chunk.choices[0]?.finish_reason;
        if (finish === "tool_calls") {
          for (const [, buf] of toolBuffers) yield { type: "tool_use_stop", id: buf.id };
          stopReason = "tool_use";
        }
        if (chunk.usage) {
          inputTokens = chunk.usage.prompt_tokens ?? inputTokens;
          outputTokens = chunk.usage.completion_tokens ?? outputTokens;
        }
      }
      yield { type: "usage", inputTokens, outputTokens };
      yield { type: "message_stop", stopReason };
    } catch (err) {
      yield { type: "error", error: err as Error };
    }
  }
}
