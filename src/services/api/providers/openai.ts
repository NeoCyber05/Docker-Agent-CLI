import OpenAI from "openai";
import type { ApiKeyStore } from "src/secrets/apiKeyStore";
import { resolveStoredApiKey } from "src/secrets/apiKeyStore";
import { toOpenAIFunction } from "../toolSchema";
import type { CallModelParams, Provider, ProviderEvent } from "../types";

export class OpenAIProvider implements Provider {
  readonly name = "openai";
  constructor(
    private env: NodeJS.ProcessEnv,
    private apiKeyStore?: ApiKeyStore,
  ) {}

  async listModels(): Promise<string[]> {
    const apiKey = await resolveStoredApiKey("openai", this.env, this.apiKeyStore);
    if (!apiKey) throw new Error("OPENAI_API_KEY not set");
    const client = new OpenAI({
      apiKey,
      ...(this.env.OPENAI_BASE_URL ? { baseURL: this.env.OPENAI_BASE_URL } : {}),
    });
    const res = await client.models.list();
    return res.data
      .map((m) => m.id)
      .filter((id): id is string => typeof id === "string" && id.length > 0)
      .sort((a, b) => a.localeCompare(b));
  }

  async *stream(params: CallModelParams): AsyncGenerator<ProviderEvent> {
    const apiKey = await resolveStoredApiKey("openai", this.env, this.apiKeyStore);
    if (!apiKey) {
      yield { type: "error", error: new Error("OPENAI_API_KEY not set") };
      return;
    }
    const client = new OpenAI({
      apiKey,
      ...(this.env.OPENAI_BASE_URL ? { baseURL: this.env.OPENAI_BASE_URL } : {}),
    });
    const model = params.model ?? this.env.OPENAI_MODEL ?? "gpt-4o-mini";
    const toolDefs = params.tools.map((t) => toOpenAIFunction(t));

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
      const stream = await client.chat.completions.create(
        {
          model,
          messages,
          ...(toolDefs.length ? { tools: toolDefs as unknown as OpenAI.ChatCompletionTool[] } : {}),
          stream: true,
          stream_options: { include_usage: true },
        },
        { signal: params.signal },
      );
      const toolBuffers = new Map<number, { id: string; name: string; args: string }>();
      let inputTokens = 0;
      let outputTokens = 0;
      let stopReason: "end_turn" | "tool_use" | "max_tokens" = "end_turn";
      for await (const chunk of stream) {
        if (params.signal?.aborted) return;
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
        if (finish === "length") {
          stopReason = "max_tokens";
        }
        if (chunk.usage) {
          inputTokens = chunk.usage.prompt_tokens ?? inputTokens;
          outputTokens = chunk.usage.completion_tokens ?? outputTokens;
        }
      }
      yield { type: "usage", inputTokens, outputTokens };
      yield { type: "message_stop", stopReason };
    } catch (err) {
      if (params.signal?.aborted) return;
      yield { type: "error", error: err as Error };
    }
  }
}
