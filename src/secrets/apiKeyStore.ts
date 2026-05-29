import { spawn } from "node:child_process";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import type { ProviderName } from "src/config";

export type ApiKeyProviderName = Extract<ProviderName, "gemini" | "openai">;
export type ApiKeySource = "env" | "saved";

export interface ApiKeyStatus {
  provider: ApiKeyProviderName;
  state: "set" | "unset";
  source?: ApiKeySource;
}

export interface ApiKeyStore {
  get(provider: ApiKeyProviderName): Promise<string | undefined>;
  set(provider: ApiKeyProviderName, value: string): Promise<void>;
  delete(provider: ApiKeyProviderName): Promise<void>;
  has(provider: ApiKeyProviderName): Promise<boolean>;
}

export const API_KEY_PROVIDERS: readonly ApiKeyProviderName[] = ["openai", "gemini"];

const API_KEY_ENV_VARS: Record<ApiKeyProviderName, string> = {
  gemini: "GEMINI_API_KEY",
  openai: "OPENAI_API_KEY",
};

interface CommandResult {
  stdout: string;
  stderr: string;
  code: number | null;
}

interface CommandOptions {
  input?: string;
  env?: NodeJS.ProcessEnv;
}

export function isApiKeyProviderName(value: unknown): value is ApiKeyProviderName {
  return typeof value === "string" && (API_KEY_PROVIDERS as readonly string[]).includes(value);
}

export function apiKeyEnvVar(provider: ApiKeyProviderName): string {
  return API_KEY_ENV_VARS[provider];
}

export async function resolveStoredApiKey(
  provider: ApiKeyProviderName,
  env: NodeJS.ProcessEnv,
  store?: ApiKeyStore,
): Promise<string | undefined> {
  const envValue = env[apiKeyEnvVar(provider)]?.trim();
  if (envValue) return envValue;
  return await store?.get(provider);
}

export async function describeApiKeyStatus(
  store: ApiKeyStore,
  env: NodeJS.ProcessEnv = process.env,
): Promise<ApiKeyStatus[]> {
  const statuses: ApiKeyStatus[] = [];
  for (const provider of API_KEY_PROVIDERS) {
    const envValue = env[apiKeyEnvVar(provider)]?.trim();
    if (envValue) {
      statuses.push({ provider, state: "set", source: "env" });
      continue;
    }
    if (await store.has(provider)) {
      statuses.push({ provider, state: "set", source: "saved" });
      continue;
    }
    statuses.push({ provider, state: "unset" });
  }
  return statuses;
}

export class MemoryApiKeyStore implements ApiKeyStore {
  private values = new Map<ApiKeyProviderName, string>();

  constructor(initial: Partial<Record<ApiKeyProviderName, string>> = {}) {
    for (const provider of API_KEY_PROVIDERS) {
      const value = initial[provider];
      if (value) this.values.set(provider, value);
    }
  }

  async get(provider: ApiKeyProviderName): Promise<string | undefined> {
    return this.values.get(provider);
  }

  async set(provider: ApiKeyProviderName, value: string): Promise<void> {
    this.values.set(provider, value);
  }

  async delete(provider: ApiKeyProviderName): Promise<void> {
    this.values.delete(provider);
  }

  async has(provider: ApiKeyProviderName): Promise<boolean> {
    return this.values.has(provider);
  }
}

export function createApiKeyStore(): ApiKeyStore {
  if (process.platform === "win32") return new WindowsDpapiApiKeyStore(defaultApiKeyDir());
  if (process.platform === "darwin") return new MacOsKeychainApiKeyStore();
  if (process.platform === "linux") return new LinuxSecretServiceApiKeyStore();
  return new UnsupportedApiKeyStore();
}

function defaultApiKeyDir(): string {
  return (
    process.env.DOCKER_AGENT_SECRET_DIR ?? path.join(os.homedir(), ".docker-agent", "api-keys")
  );
}

function apiKeyFile(baseDir: string, provider: ApiKeyProviderName): string {
  return path.join(baseDir, `${provider}.credential`);
}

function credentialService(provider: ApiKeyProviderName): string {
  return `docker-agent:${provider}:api-key`;
}

function runCommand(
  command: string,
  args: string[],
  options: CommandOptions = {},
): Promise<CommandResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
      ...(options.env ? { env: options.env } : {}),
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
    });
    child.on("error", reject);
    child.on("close", (code) => {
      resolve({ stdout, stderr, code });
    });
    if (options.input !== undefined) child.stdin.end(options.input);
    else child.stdin.end();
  });
}

async function runRequired(
  command: string,
  args: string[],
  options: CommandOptions = {},
): Promise<string> {
  const result = await runCommand(command, args, options);
  if (result.code !== 0) {
    throw new Error(result.stderr.trim() || `${command} exited with ${result.code}`);
  }
  return result.stdout;
}

class WindowsDpapiApiKeyStore implements ApiKeyStore {
  constructor(private baseDir: string) {}

  async get(provider: ApiKeyProviderName): Promise<string | undefined> {
    const file = apiKeyFile(this.baseDir, provider);
    const script = [
      "$ErrorActionPreference = 'Stop'",
      "$path = $env:DOCKER_AGENT_API_KEY_PATH",
      "if (!(Test-Path -LiteralPath $path)) { exit 3 }",
      "$encrypted = Get-Content -LiteralPath $path -Raw",
      "$secure = ConvertTo-SecureString -String $encrypted",
      "$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)",
      "try { [Console]::Out.Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)) }",
      "finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }",
    ].join("\n");
    const result = await runCommand(
      "powershell.exe",
      ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
      { env: { ...process.env, DOCKER_AGENT_API_KEY_PATH: file } },
    );
    if (result.code === 3) return undefined;
    if (result.code !== 0) throw new Error(result.stderr.trim() || "Failed to read API key");
    return result.stdout || undefined;
  }

  async set(provider: ApiKeyProviderName, value: string): Promise<void> {
    await fs.mkdir(this.baseDir, { recursive: true, mode: 0o700 });
    const file = apiKeyFile(this.baseDir, provider);
    const script = [
      "$ErrorActionPreference = 'Stop'",
      "$path = $env:DOCKER_AGENT_API_KEY_PATH",
      "$secret = $env:DOCKER_AGENT_API_KEY_VALUE",
      "$secure = ConvertTo-SecureString -String $secret -AsPlainText -Force",
      "$encrypted = ConvertFrom-SecureString -SecureString $secure",
      "Set-Content -LiteralPath $path -Value $encrypted -NoNewline -Encoding UTF8",
    ].join("\n");
    await runRequired(
      "powershell.exe",
      ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
      {
        env: {
          ...process.env,
          DOCKER_AGENT_API_KEY_PATH: file,
          DOCKER_AGENT_API_KEY_VALUE: value,
        },
      },
    );
  }

  async delete(provider: ApiKeyProviderName): Promise<void> {
    await fs.rm(apiKeyFile(this.baseDir, provider), { force: true });
  }

  async has(provider: ApiKeyProviderName): Promise<boolean> {
    try {
      await fs.access(apiKeyFile(this.baseDir, provider));
      return true;
    } catch {
      return false;
    }
  }
}

class MacOsKeychainApiKeyStore implements ApiKeyStore {
  async get(provider: ApiKeyProviderName): Promise<string | undefined> {
    const result = await runCommand("security", [
      "find-generic-password",
      "-a",
      "docker-agent",
      "-s",
      credentialService(provider),
      "-w",
    ]);
    if (result.code !== 0) return undefined;
    return result.stdout.trim() || undefined;
  }

  async set(provider: ApiKeyProviderName, value: string): Promise<void> {
    await runRequired("security", [
      "add-generic-password",
      "-a",
      "docker-agent",
      "-s",
      credentialService(provider),
      "-w",
      value,
      "-U",
    ]);
  }

  async delete(provider: ApiKeyProviderName): Promise<void> {
    await runCommand("security", [
      "delete-generic-password",
      "-a",
      "docker-agent",
      "-s",
      credentialService(provider),
    ]);
  }

  async has(provider: ApiKeyProviderName): Promise<boolean> {
    return (await this.get(provider)) !== undefined;
  }
}

class LinuxSecretServiceApiKeyStore implements ApiKeyStore {
  async get(provider: ApiKeyProviderName): Promise<string | undefined> {
    const result = await runCommand("secret-tool", [
      "lookup",
      "application",
      "docker-agent",
      "provider",
      provider,
    ]);
    if (result.code !== 0) return undefined;
    return result.stdout.trim() || undefined;
  }

  async set(provider: ApiKeyProviderName, value: string): Promise<void> {
    await runRequired(
      "secret-tool",
      [
        "store",
        "--label",
        credentialService(provider),
        "application",
        "docker-agent",
        "provider",
        provider,
      ],
      { input: value },
    );
  }

  async delete(provider: ApiKeyProviderName): Promise<void> {
    await runCommand("secret-tool", ["clear", "application", "docker-agent", "provider", provider]);
  }

  async has(provider: ApiKeyProviderName): Promise<boolean> {
    return (await this.get(provider)) !== undefined;
  }
}

class UnsupportedApiKeyStore implements ApiKeyStore {
  async get(): Promise<string | undefined> {
    return undefined;
  }

  async set(): Promise<void> {
    throw new Error("No persistent credential backend is available on this platform");
  }

  async delete(): Promise<void> {}

  async has(): Promise<boolean> {
    return false;
  }
}
