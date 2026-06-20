import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  destroyStackPrompt,
  dispatchSecretsList,
  dispatchStacks,
  dispatchYaml,
  formatStacksTable,
  isDestroyAllPrompt,
  parseDirectDestroyStack,
} from "src/slashDispatch";
import { StateStore } from "src/state/StateStore";
import type { StackDefinition } from "src/types/stack";
import { afterEach, beforeEach, describe, expect, test } from "vitest";

function makeDef(
  name: string,
  extras?: Partial<StackDefinition["services"]["web"]>,
): StackDefinition {
  return {
    "x-docker-agent": {
      name,
      createdAt: "2026-05-26T00:00:00Z",
      lastApplied: "2026-06-01T12:00:00Z",
      intent: "test",
      provider: "gemini",
      generatedBy: "test",
      envFileSources: {
        web: { generated: true, path: ".docker-agent/secrets/web.env", addedKeys: ["API_TOKEN"] },
      },
    },
    services: {
      web: {
        image: "nginx:1.27-alpine",
        environment: { POSTGRES_PASSWORD: "super-secret", PORT: "8080" },
        ...extras,
      },
    },
  };
}

describe("slashDispatch", () => {
  let tmpRoot: string;
  let store: StateStore;
  let ctx: { cwd: string; stateStore: StateStore };

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "slash-dispatch-"));
    store = new StateStore(path.join(tmpRoot, ".docker-agent"));
    ctx = { cwd: tmpRoot, stateStore: store };
  });

  afterEach(() => {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  test("formatStacksTable shows empty message when no stacks", () => {
    expect(formatStacksTable([])).toContain("Managed stacks");
    expect(formatStacksTable([])).toContain("No stacks defined");
  });

  test("dispatchStacks renders markdown table", () => {
    store.write("webapp", makeDef("webapp"));
    const text = dispatchStacks(ctx);
    expect(text).toContain("| Name | Services | Last applied |");
    expect(text).toContain("| webapp | 1 |");
  });

  test("dispatchYaml redacts secret environment values", () => {
    store.write("webapp", makeDef("webapp"));
    const result = dispatchYaml("webapp", ctx);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.text).toContain("POSTGRES_PASSWORD");
    expect(result.text).toContain("***");
    expect(result.text).not.toContain("super-secret");
    expect(result.text).toContain('PORT: "8080"');
  });

  test("dispatchYaml returns error for missing stack", () => {
    const result = dispatchYaml("missing", ctx);
    expect(result).toEqual({ ok: false, error: "stack missing not found" });
  });

  test("dispatchSecretsList returns tracked secret key names only", () => {
    store.write("webapp", makeDef("webapp"));
    const result = dispatchSecretsList("webapp", ctx);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.text).toContain("API_TOKEN");
    expect(result.text).toContain("POSTGRES_PASSWORD");
    expect(result.text).not.toContain("super-secret");
  });

  test("destroyStackPrompt and parseDirectDestroyStack round-trip slash rewrite", () => {
    expect(destroyStackPrompt("webapp")).toBe("Destroy stack webapp");
    expect(destroyStackPrompt("webapp", true)).toBe("Destroy stack webapp with volumes");
    expect(parseDirectDestroyStack("Destroy stack webapp")).toEqual({
      stackName: "webapp",
      removeVolumes: false,
    });
    expect(parseDirectDestroyStack("destroy webapp with volumes")).toEqual({
      stackName: "webapp",
      removeVolumes: true,
    });
    expect(parseDirectDestroyStack("destroy all stacks")).toBeNull();
    expect(isDestroyAllPrompt("Destroy all stacks")).toBe(true);
    expect(isDestroyAllPrompt("destroy all stacks")).toBe(true);
  });

  test("dispatchSecretsList reports when no keys are tracked", () => {
    const def = makeDef("plain");
    def["x-docker-agent"].envFileSources = {};
    def.services.web = { image: "nginx:1.27-alpine", environment: { PORT: "8080" } };
    store.write("plain", def);
    const result = dispatchSecretsList("plain", ctx);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.text).toContain("No secret keys tracked");
  });
});
