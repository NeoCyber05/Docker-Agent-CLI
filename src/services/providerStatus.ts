import { PROVIDER_NAMES, type ProviderName } from "src/config";
import {
  type ApiKeyStore,
  isApiKeyProviderName,
  resolveStoredApiKey,
} from "src/secrets/apiKeyStore";
import type { Provider } from "src/services/api/types";

export interface ProviderStatus {
  provider: ProviderName;
  connected: boolean;
  modelCount?: number;
  reason?: string;
}

export async function isApiKeyProviderConnected(
  provider: ProviderName,
  apiKeyStore: ApiKeyStore,
  env: NodeJS.ProcessEnv = process.env,
): Promise<boolean> {
  if (!isApiKeyProviderName(provider)) return false;
  return Boolean(await resolveStoredApiKey(provider, env, apiKeyStore));
}

export async function getProviderStatuses(opts: {
  apiKeyStore: ApiKeyStore;
  providers: Partial<Record<ProviderName, Provider>>;
  env?: NodeJS.ProcessEnv;
}): Promise<ProviderStatus[]> {
  const env = opts.env ?? process.env;
  return Promise.all(
    PROVIDER_NAMES.map(async (provider): Promise<ProviderStatus> => {
      if (isApiKeyProviderName(provider)) {
        const connected = await isApiKeyProviderConnected(provider, opts.apiKeyStore, env);
        return { provider, connected, ...(connected ? {} : { reason: "API key not set" }) };
      }
      // ollama
      const instance = opts.providers.ollama;
      if (!instance || typeof instance.listModels !== "function") {
        return { provider, connected: false, reason: "Cannot probe Ollama" };
      }
      try {
        const models = await instance.listModels();
        return { provider, connected: true, modelCount: models.length };
      } catch (err) {
        return {
          provider,
          connected: false,
          reason: err instanceof Error ? err.message : String(err),
        };
      }
    }),
  );
}
