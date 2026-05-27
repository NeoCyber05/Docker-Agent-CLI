import { type FunctionDeclaration, GoogleGenerativeAI } from "@google/generative-ai";
import { stripForGemini, toGeminiFunctionDeclaration } from "../toolSchema";
import type { CallModelParams, Provider, ProviderEvent } from "../types";

export class GeminiProvider implements Provider {
  readonly name = "gemini";
  constructor(private env: NodeJS.ProcessEnv) {}

  async *stream(params: CallModelParams): AsyncGenerator<ProviderEvent> {
    const apiKey = this.env.GEMINI_API_KEY;
    if (!apiKey) {
      yield { type: "error", error: new Error("GEMINI_API_KEY not set") };
      return;
    }
    const modelId = params.model ?? this.env.GEMINI_MODEL ?? "gemini-2.0-flash-exp";
    const client = new GoogleGenerativeAI(apiKey);
    const tools = params.tools;
    const toolUseToName = new Map<string, string>();
    for (const m of params.messages) {
      if (m.role === "assistant") {
        for (const b of m.content) {
          if (b.type === "tool_use") toolUseToName.set(b.id, b.name);
        }
      }
    }
    const model = client.getGenerativeModel({
      model: modelId,
      systemInstruction: params.system,
      ...(tools.length
        ? {
            tools: [
              {
                functionDeclarations: tools.map((t) => toGeminiFunctionDeclaration(t)),
              },
            ],
          }
        : {}),
    });

    const contents = params.messages.map((m) => {
      if (m.role === "user") return { role: "user", parts: [{ text: m.content }] };
      if (m.role === "assistant")
        return {
          role: "model",
          parts: m.content.map((b) =>
            b.type === "text"
              ? { text: b.text }
              : { functionCall: { name: b.name, args: b.input as Record<string, unknown> } },
          ),
        };
      return {
        role: "function",
        parts: [
          {
            functionResponse: {
              name: toolUseToName.get(m.toolUseId) ?? m.toolUseId,
              response: { content: m.content },
            },
          },
        ],
      };
    });

    try {
      const result = await model.generateContentStream({ contents });
      let inputTokens = 0;
      let outputTokens = 0;
      let toolCallIdx = 0;
      for await (const chunk of result.stream) {
        for (const cand of chunk.candidates ?? []) {
          for (const part of cand.content.parts ?? []) {
            if (part.text) {
              yield { type: "text_delta", text: part.text };
            }
            if (part.functionCall) {
              const id = `gemini-${toolCallIdx++}`;
              yield { type: "tool_use_start", id, name: part.functionCall.name };
              yield {
                type: "tool_use_delta",
                id,
                argsPartialJson: JSON.stringify(part.functionCall.args),
              };
              yield { type: "tool_use_stop", id };
            }
          }
        }
        const usage = chunk.usageMetadata;
        if (usage) {
          inputTokens = usage.promptTokenCount ?? inputTokens;
          outputTokens = usage.candidatesTokenCount ?? outputTokens;
        }
      }
      yield { type: "usage", inputTokens, outputTokens };
      yield { type: "message_stop", stopReason: "end_turn" };
    } catch (err) {
      yield { type: "error", error: err as Error };
    }
  }
}
