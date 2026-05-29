import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  MemoryApiKeyStore,
  createApiKeyStore,
  describeApiKeyStatus,
  resolveStoredApiKey,
} from "src/secrets/apiKeyStore";
import { afterEach, describe, expect, test } from "vitest";

describe("api key store", () => {
  let originalEnv: NodeJS.ProcessEnv | undefined;
  const tmpDirs: string[] = [];

  afterEach(() => {
    if (originalEnv) process.env = originalEnv;
    originalEnv = undefined;
    for (const tmp of tmpDirs.splice(0)) {
      fs.rmSync(tmp, { recursive: true, force: true });
    }
  });

  test("describes status for each API-key provider without exposing values", async () => {
    const store = new MemoryApiKeyStore({ openai: "sk-test-value" });

    const status = await describeApiKeyStatus(store, {});

    expect(status).toEqual([
      { provider: "openai", state: "set", source: "saved" },
      { provider: "gemini", state: "unset" },
    ]);
    expect(JSON.stringify(status)).not.toContain("sk-test-value");
  });

  test("environment API keys override saved API keys", async () => {
    const store = new MemoryApiKeyStore({ openai: "saved-openai-key" });

    await expect(
      resolveStoredApiKey("openai", { OPENAI_API_KEY: "env-openai-key" }, store),
    ).resolves.toBe("env-openai-key");
  });

  test("falls back to the saved API key when the environment is unset", async () => {
    const store = new MemoryApiKeyStore({ gemini: "saved-gemini-key" });

    await expect(resolveStoredApiKey("gemini", {}, store)).resolves.toBe("saved-gemini-key");
  });

  test("windows persistent store writes and reads a key from a configured directory", async () => {
    if (process.platform !== "win32") return;
    originalEnv = { ...process.env };
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "docker-agent-api-key-store-"));
    tmpDirs.push(tmp);
    process.env.DOCKER_AGENT_SECRET_DIR = tmp;
    const store = createApiKeyStore();

    await store.set("gemini", "test-gemini-key");

    await expect(store.get("gemini")).resolves.toBe("test-gemini-key");
    await expect(store.has("gemini")).resolves.toBe(true);
  }, 60_000);
});
