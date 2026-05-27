import type { ProviderName } from "src/config";
import { GeminiProvider } from "./providers/gemini";
import { OllamaProvider } from "./providers/ollama";
import { OpenAIProvider } from "./providers/openai";
import type { CallModelParams, Provider, ProviderEvent, ToolSchema } from "./types";

export function resolveProviderForRequest(
  name: ProviderName,
  env: NodeJS.ProcessEnv = process.env,
): Provider & { name: string } {
  switch (name) {
    case "gemini":
      return new GeminiProvider(env);
    case "openai":
      return new OpenAIProvider(env);
    case "ollama":
      return new OllamaProvider(env);
    default:
      throw new Error(`unknown provider: ${String(name)}`);
  }
}

export async function* callModel(
  providerName: ProviderName,
  params: CallModelParams,
): AsyncGenerator<ProviderEvent> {
  const provider = resolveProviderForRequest(providerName);
  yield* provider.stream(params);
}

export type { Provider, ProviderEvent, CallModelParams, ToolSchema };
