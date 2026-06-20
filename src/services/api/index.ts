import type { ProviderName } from "src/config";
import type { ApiKeyStore } from "src/secrets/apiKeyStore";
import { GeminiProvider } from "./providers/gemini";
import { OllamaProvider } from "./providers/ollama";
import { OpenAIProvider } from "./providers/openai";
import { OpenRouterProvider } from "./providers/openrouter";
import type { CallModelParams, Provider, ProviderEvent } from "./types";

export function resolveProviderForRequest(
  name: ProviderName,
  env: NodeJS.ProcessEnv = process.env,
  options: { apiKeyStore?: ApiKeyStore } = {},
): Provider {
  switch (name) {
    case "gemini":
      return new GeminiProvider(env, options.apiKeyStore);
    case "openai":
      return new OpenAIProvider(env, options.apiKeyStore);
    case "ollama":
      return new OllamaProvider(env);
    case "openrouter":
      return new OpenRouterProvider(env, options.apiKeyStore);
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

export type { Provider, ProviderEvent, CallModelParams };
