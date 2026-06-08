import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  isValidProvider,
  loadUserConfig,
  projectStateDir,
  resolveProvider,
  userConfigPath,
} from "src/config";
import { afterEach, beforeEach, describe, expect, test } from "vitest";

describe("config resolution", () => {
  let originalCwd: string;
  let originalEnv: NodeJS.ProcessEnv;
  let tmpDir: string;

  beforeEach(() => {
    originalCwd = process.cwd();
    originalEnv = { ...process.env };
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "docker-agent-config-test-"));
    // Isolate from any real ~/.docker-agent/config.json on the developer's machine.
    // Points at a non-existent file so loadUserConfig() yields defaults unless a
    // test explicitly writes its own config and overrides this.
    process.env.DOCKER_AGENT_CONFIG = path.join(tmpDir, "isolated-config.json");
  });

  afterEach(() => {
    process.chdir(originalCwd);
    process.env = originalEnv;
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {
      /* ignore cleanup errors */
    }
  });

  test("userConfigPath defaults to ~/.docker-agent/config.json", () => {
    Reflect.deleteProperty(process.env, "DOCKER_AGENT_CONFIG");
    expect(userConfigPath()).toBe(path.join(os.homedir(), ".docker-agent", "config.json"));
  });

  test("userConfigPath honours DOCKER_AGENT_CONFIG override", () => {
    process.env.DOCKER_AGENT_CONFIG = "/tmp/custom.json";
    expect(userConfigPath()).toBe("/tmp/custom.json");
  });

  test("projectStateDir is cwd/.docker-agent", () => {
    expect(projectStateDir()).toBe(path.join(process.cwd(), ".docker-agent"));
  });

  test("loadUserConfig returns defaults when file missing", () => {
    process.env.DOCKER_AGENT_CONFIG = path.join(tmpDir, "missing.json");
    expect(loadUserConfig()).toEqual({
      provider: "gemini",
      model: undefined,
      defaults: { autoApproveNonDestructive: false },
      theme: "dark",
    });
  });

  test("loadUserConfig loads valid config and merges with defaults", () => {
    const configPath = path.join(tmpDir, "config.json");
    fs.writeFileSync(configPath, JSON.stringify({ provider: "openai", theme: "light" }));
    process.env.DOCKER_AGENT_CONFIG = configPath;
    expect(loadUserConfig()).toEqual({
      provider: "openai",
      model: undefined,
      defaults: { autoApproveNonDestructive: false },
      theme: "light",
    });
  });

  test("loadUserConfig falls back to defaults on invalid JSON", () => {
    const configPath = path.join(tmpDir, "config.json");
    fs.writeFileSync(configPath, "not-json");
    process.env.DOCKER_AGENT_CONFIG = configPath;
    expect(loadUserConfig()).toEqual({
      provider: "gemini",
      model: undefined,
      defaults: { autoApproveNonDestructive: false },
      theme: "dark",
    });
  });

  test("resolveProvider priority: flag > env > config > default", () => {
    process.env.DOCKER_AGENT_PROVIDER = "openai";
    expect(resolveProvider({ flag: "ollama" })).toBe("ollama");
    expect(resolveProvider({})).toBe("openai");
    Reflect.deleteProperty(process.env, "DOCKER_AGENT_PROVIDER");
    expect(resolveProvider({})).toBe("gemini");
  });

  test("resolveProvider ignores invalid flag and falls through", () => {
    expect(resolveProvider({ flag: "bad-provider" })).toBe("gemini");
  });

  test("resolveProvider ignores invalid env and falls through to config", () => {
    const configPath = path.join(tmpDir, "config.json");
    fs.writeFileSync(configPath, JSON.stringify({ provider: "ollama" }));
    process.env.DOCKER_AGENT_CONFIG = configPath;
    process.env.DOCKER_AGENT_PROVIDER = "invalid";
    expect(resolveProvider({})).toBe("ollama");
  });

  test("isValidProvider accepts only known providers", () => {
    expect(isValidProvider("gemini")).toBe(true);
    expect(isValidProvider("openai")).toBe(true);
    expect(isValidProvider("ollama")).toBe(true);
    expect(isValidProvider("unknown")).toBe(false);
    expect(isValidProvider(42)).toBe(false);
  });
});
