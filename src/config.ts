import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

export type ProviderName = "gemini" | "openai" | "ollama";

const PROVIDER_NAMES: readonly ProviderName[] = ["gemini", "openai", "ollama"];

export function isValidProvider(value: unknown): value is ProviderName {
  return typeof value === "string" && (PROVIDER_NAMES as readonly string[]).includes(value);
}

export interface UserConfig {
  provider: ProviderName;
  model: string | undefined;
  defaults: { autoApproveNonDestructive: boolean };
  theme: "dark" | "light";
}

export function userConfigPath(): string {
  return process.env.DOCKER_AGENT_CONFIG ?? path.join(os.homedir(), ".docker-agent", "config.json");
}

export function projectStateDir(): string {
  return path.join(process.cwd(), ".docker-agent");
}

const DEFAULTS: UserConfig = {
  provider: "gemini",
  model: undefined,
  defaults: { autoApproveNonDestructive: false },
  theme: "dark",
};

export function loadUserConfig(): UserConfig {
  const p = userConfigPath();
  if (!fs.existsSync(p)) return DEFAULTS;
  try {
    const raw = JSON.parse(fs.readFileSync(p, "utf-8")) as Partial<UserConfig>;
    return {
      provider: isValidProvider(raw.provider) ? raw.provider : DEFAULTS.provider,
      model: raw.model,
      defaults: { ...DEFAULTS.defaults, ...(raw.defaults ?? {}) },
      theme: raw.theme ?? DEFAULTS.theme,
    };
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn("[docker-agent] Failed to load user config, using defaults:", err);
    return DEFAULTS;
  }
}

export function resolveProvider(opts: { flag?: string }): ProviderName {
  if (opts.flag && isValidProvider(opts.flag)) return opts.flag;
  if (process.env.DOCKER_AGENT_PROVIDER && isValidProvider(process.env.DOCKER_AGENT_PROVIDER)) {
    return process.env.DOCKER_AGENT_PROVIDER;
  }
  return loadUserConfig().provider;
}
