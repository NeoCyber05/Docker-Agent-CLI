import { type FunctionDeclaration, GoogleGenerativeAI } from "@google/generative-ai";
import type { ApiKeyStore } from "src/secrets/apiKeyStore";
import { resolveStoredApiKey } from "src/secrets/apiKeyStore";
import { stripForGemini, toGeminiFunctionDeclaration } from "../toolSchema";
import type { CallModelParams, Provider, ProviderEvent } from "../types";

export class GeminiProvider implements Provider {
  readonly name = "gemini";
  constructor(
    private env: NodeJS.ProcessEnv,
    private apiKeyStore?: ApiKeyStore,
  ) {}

  async listModels(): Promise<string[]> {
    const apiKey = await resolveStoredApiKey("gemini", this.env, this.apiKeyStore);
    if (!apiKey) throw new Error("GEMINI_API_KEY not set");

    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models?key=${apiKey}`,
    );
    if (!res.ok) {
      const err = (await res.json().catch(() => ({}))) as any;
      throw new Error(`Failed to fetch models: ${err.error?.message || res.statusText}`);
    }
    const data = (await res.json()) as { models: { name: string }[] };
    return data.models
      .map((m) => m.name.replace(/^models\//, ""))
      .filter((id) => id.includes("gemini"))
      .sort((a, b) => a.localeCompare(b));
  }

  async *stream(params: CallModelParams): AsyncGenerator<ProviderEvent> {
    const apiKey = await resolveStoredApiKey("gemini", this.env, this.apiKeyStore);
    if (!apiKey) {
      yield { type: "error", error: new Error("GEMINI_API_KEY not set") };
      return;
    }
    const modelId = params.model ?? this.env.GEMINI_MODEL ?? "gemini-2.0-flash";
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
      let hasOutput = false;
      let lastFinishReason: string | undefined;
      for await (const chunk of result.stream) {
        // Check for safety blocks on the prompt itself
        const pf = (chunk as any).promptFeedback;
        if (pf?.blockReason) {
          yield {
            type: "error",
            error: new Error(`Prompt blocked by Gemini safety filter: ${pf.blockReason}`),
          };
          return;
        }

        for (const cand of chunk.candidates ?? []) {
          // Track finish reason (e.g. SAFETY, RECITATION, MAX_TOKENS)
          if (cand.finishReason) {
            lastFinishReason = cand.finishReason;
          }

          // Guard against undefined content (common during thinking phase)
          const parts = cand.content?.parts ?? [];

          for (const part of parts) {
            // Skip thinking-only parts (Gemini 2.5 thinking models)
            if ((part as any).thought === true && !part.functionCall) {
              // Thinking part — don't emit as visible text
              continue;
            }

            if (part.text) {
              hasOutput = true;
              yield { type: "text_delta", text: part.text };
            }
            if (part.functionCall) {
              hasOutput = true;
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

      // Check for non-success finish reasons
      if (
        lastFinishReason &&
        lastFinishReason !== "STOP" &&
        lastFinishReason !== "MAX_TOKENS" &&
        !hasOutput
      ) {
        yield {
          type: "error",
          error: new Error(
            `Gemini response ended with reason: ${lastFinishReason}. The model may have blocked the response.`,
          ),
        };
        return;
      }

      // If the stream completed without producing any content, report it
      if (!hasOutput) {
        yield {
          type: "error",
          error: new Error(
            `Gemini returned an empty response for model "${modelId}". ` +
              "This may happen if the model is unsupported by the current SDK version, " +
              "or if a safety filter silently blocked the output.",
          ),
        };
        return;
      }

      yield { type: "usage", inputTokens, outputTokens };
      yield { type: "message_stop", stopReason: "end_turn" };
    } catch (err) {
      yield { type: "error", error: err as Error };
    }
  }
}
