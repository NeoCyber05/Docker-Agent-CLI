import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { MemoryApiKeyStore } from "src/secrets/apiKeyStore";
import { SLASH_COMMAND_DEFS, resolveSlashKey, routeSlashCommand } from "src/slashRouter";
import { StateStore } from "src/state/StateStore";
import type { StackDefinition } from "src/types/stack";
import { afterEach, beforeEach, describe, expect, test } from "vitest";

function makeCtx(tmpRoot: string) {
  return {
    cwd: tmpRoot,
    stateStore: new StateStore(path.join(tmpRoot, ".docker-agent")),
    activeProviderName: "gemini" as const,
    apiKeyStore: new MemoryApiKeyStore(),
    hasLatestTool: true,
  };
}

describe("resolveSlashKey", () => {
  test("resolves single-token commands", () => {
    expect(resolveSlashKey(["/help"])).toBe("/help");
    expect(resolveSlashKey(["/stacks"])).toBe("/stacks");
  });

  test("resolves multi-token commands with longest match", () => {
    expect(resolveSlashKey(["/secrets", "list"])).toBe("/secrets list");
    expect(resolveSlashKey(["/secrets", "rotate", "s", "svc"])).toBe("/secrets rotate");
    expect(resolveSlashKey(["/queue", "remove", "2"])).toBe("/queue remove");
    expect(resolveSlashKey(["/destroy", "all"])).toBe("/destroy all");
    expect(resolveSlashKey(["/destroy", "ALL"])).toBe("/destroy all");
  });

  test("returns null for unknown commands", () => {
    expect(resolveSlashKey(["/not-a-command"])).toBeNull();
  });
});

describe("routeSlashCommand", () => {
  let tmpRoot: string;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "slash-router-"));
  });

  afterEach(() => {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  test("unknown command emits error and is handled", async () => {
    const result = await routeSlashCommand("/nope", makeCtx(tmpRoot));
    expect(result.handled).toBe(true);
    expect(result.effects).toEqual(
      expect.arrayContaining([
        { type: "emit_user_text", text: "/nope" },
        expect.objectContaining({
          type: "emit_error",
          message: "Unknown slash command: /nope. Try /help.",
        }),
      ]),
    );
  });

  test("registry metadata covers every SLASH_COMMAND_DEFS entry", () => {
    expect(SLASH_COMMAND_DEFS.length).toBeGreaterThanOrEqual(20);
    for (const def of SLASH_COMMAND_DEFS) {
      expect(def.usage).toMatch(/^\//);
      expect(def.description.length).toBeGreaterThan(0);
      expect(def.insertText).toMatch(/^\//);
    }
  });
});

function makeDef(name: string): StackDefinition {
  return {
    "x-docker-agent": {
      name,
      createdAt: "2026-05-26T00:00:00Z",
      lastApplied: "2026-06-01T12:00:00Z",
      intent: "test",
      provider: "gemini",
      generatedBy: "test",
      envFileSources: {
        web: { generated: true, path: ".docker-agent/env/web.env", addedKeys: ["API_TOKEN"] },
      },
    },
    services: {
      web: {
        image: "nginx:1.27-alpine",
        environment: { POSTGRES_PASSWORD: "secret", PORT: "8080" },
      },
    },
  };
}

describe("routeSlashCommand — data dispatch", () => {
  let tmpRoot: string;
  let ctx: ReturnType<typeof makeCtx>;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "slash-router-data-"));
    ctx = makeCtx(tmpRoot);
  });

  afterEach(() => {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  test("/help emits formatted help", async () => {
    const result = await routeSlashCommand("/help", ctx);
    expect(result.effects).toEqual(
      expect.arrayContaining([
        { type: "emit_user_text", text: "/help" },
        expect.objectContaining({ type: "emit_assistant_text" }),
      ]),
    );
    const assistant = result.effects.find((e) => e.type === "emit_assistant_text");
    expect(assistant && "delta" in assistant ? assistant.delta : "").toContain(
      "Supported slash commands",
    );
  });

  test("/stacks emits table without LLM submit", async () => {
    const result = await routeSlashCommand("/stacks", ctx);
    expect(result.handled).toBe(true);
    expect(result.effects.some((e) => e.type === "submit_prompt")).toBe(false);
    const assistant = result.effects.find((e) => e.type === "emit_assistant_text");
    expect(assistant && "delta" in assistant ? assistant.delta : "").toContain("Managed stacks");
  });

  test("/yaml requires stack arg", async () => {
    const result = await routeSlashCommand("/yaml", ctx);
    expect(result.effects).toEqual(
      expect.arrayContaining([
        { type: "emit_user_text", text: "/yaml" },
        { type: "emit_error", message: "Usage: /yaml <stack>" },
      ]),
    );
  });

  test("/yaml emits redacted yaml for existing stack", async () => {
    ctx.stateStore.write("webapp", makeDef("webapp"));
    const result = await routeSlashCommand("/yaml webapp", ctx);
    const assistant = result.effects.find((e) => e.type === "emit_assistant_text");
    const delta = assistant && "delta" in assistant ? assistant.delta : "";
    expect(delta).toContain("***");
    expect(delta).not.toContain("secret");
  });

  test("/secrets list requires stack arg", async () => {
    const result = await routeSlashCommand("/secrets list", ctx);
    expect(
      result.effects.some((e) => e.type === "emit_error" && e.message.includes("Usage:")),
    ).toBe(true);
  });

  test("/secrets bare shows usage", async () => {
    const result = await routeSlashCommand("/secrets", ctx);
    expect(result.effects).toEqual(
      expect.arrayContaining([
        {
          type: "emit_error",
          message: "Usage: /secrets list <stack> | /secrets rotate <stack> <service>",
        },
      ]),
    );
  });
});

describe("routeSlashCommand — prompt rewrite", () => {
  let tmpRoot: string;
  let ctx: ReturnType<typeof makeCtx>;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "slash-router-prompt-"));
    ctx = makeCtx(tmpRoot);
  });

  afterEach(() => {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  test("/status rewrites to agent prompt", async () => {
    const result = await routeSlashCommand("/status webapp", ctx);
    expect(result.handled).toBe(true);
    expect(result.effects).toEqual([
      { type: "emit_user_text", text: "/status webapp" },
      { type: "submit_prompt", prompt: "Show status and drift for stack webapp" },
    ]);
  });

  test("/status without arg shows usage error", async () => {
    const result = await routeSlashCommand("/status", ctx);
    expect(
      result.effects.some((e) => e.type === "emit_error" && e.message === "Usage: /status <stack>"),
    ).toBe(true);
  });

  test("/destroy all rewrites case-insensitively", async () => {
    const result = await routeSlashCommand("/destroy ALL", ctx);
    expect(result.effects).toEqual([
      { type: "emit_user_text", text: "/destroy ALL" },
      { type: "submit_prompt", prompt: "Destroy all stacks" },
    ]);
  });

  test("/destroy <stack> rewrites to destroy prompt", async () => {
    const result = await routeSlashCommand("/destroy webapp", ctx);
    expect(result.effects).toEqual([
      { type: "emit_user_text", text: "/destroy webapp" },
      { type: "submit_prompt", prompt: "Destroy stack webapp" },
    ]);
  });

  test("/destroy without arg shows usage error", async () => {
    const result = await routeSlashCommand("/destroy", ctx);
    expect(
      result.effects.some(
        (e) => e.type === "emit_error" && e.message === "Usage: /destroy <stack>",
      ),
    ).toBe(true);
  });

  test("/secrets rotate rewrites to agent prompt", async () => {
    const result = await routeSlashCommand("/secrets rotate mystack web", ctx);
    expect(result.effects).toEqual([
      { type: "emit_user_text", text: "/secrets rotate mystack web" },
      { type: "submit_prompt", prompt: "Rotate secrets for service web in stack mystack" },
    ]);
  });

  test("/secrets rotate with missing args shows usage error", async () => {
    const result = await routeSlashCommand("/secrets rotate mystack", ctx);
    expect(
      result.effects.some((e) => e.type === "emit_error" && e.message.includes("Usage:")),
    ).toBe(true);
  });
});

describe("routeSlashCommand — UI effects", () => {
  let tmpRoot: string;
  let ctx: ReturnType<typeof makeCtx>;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "slash-router-ui-"));
    ctx = makeCtx(tmpRoot);
  });

  afterEach(() => {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  test("/exit emits exit effect", async () => {
    const result = await routeSlashCommand("/exit", ctx);
    expect(result.effects).toEqual([{ type: "exit" }]);
  });

  test("/clear emits clear_session effect", async () => {
    const result = await routeSlashCommand("/clear", ctx);
    expect(result.effects).toEqual([{ type: "clear_session" }]);
  });

  test("/cancel emits cancel_current", async () => {
    const result = await routeSlashCommand("/cancel", ctx);
    expect(result.effects).toEqual([{ type: "cancel_current" }]);
  });

  test("/connect opens provider connect dialog", async () => {
    const result = await routeSlashCommand("/connect", ctx);
    expect(result.effects).toEqual([
      { type: "emit_user_text", text: "/connect" },
      { type: "open_provider_connect" },
    ]);
  });

  test("/models opens model picker", async () => {
    const result = await routeSlashCommand("/models", ctx);
    expect(result.effects).toEqual([
      { type: "emit_user_text", text: "/models" },
      { type: "open_model_picker" },
    ]);
  });

  test("/model without arg opens picker", async () => {
    const result = await routeSlashCommand("/model", ctx);
    expect(result.effects).toEqual([
      { type: "emit_user_text", text: "/model" },
      { type: "open_model_picker" },
    ]);
  });

  test("/model with valid provider/model emits set_model", async () => {
    const result = await routeSlashCommand("/model openai/gpt-4.1-mini", ctx);
    expect(result.effects).toEqual([
      { type: "emit_user_text", text: "/model openai/gpt-4.1-mini" },
      { type: "set_model", provider: "openai", model: "gpt-4.1-mini" },
      { type: "emit_assistant_text", delta: "Model set to gpt-4.1-mini (openai)" },
    ]);
  });

  test("/model with invalid arg emits error", async () => {
    const result = await routeSlashCommand("/model !!!", ctx);
    expect(result.effects.some((e) => e.type === "emit_error")).toBe(true);
  });

  test("/logs requires stack", async () => {
    const result = await routeSlashCommand("/logs", ctx);
    expect(
      result.effects.some((e) => e.type === "emit_error" && e.message.includes("Usage:")),
    ).toBe(true);
  });

  test("/logs emits start_log_pane", async () => {
    const result = await routeSlashCommand("/logs webapp api", ctx);
    expect(result.effects).toEqual([
      { type: "start_log_pane", stackName: "webapp", service: "api" },
    ]);
  });

  test("/details without tool emits error", async () => {
    const result = await routeSlashCommand("/details", { ...ctx, hasLatestTool: false });
    expect(result.effects).toEqual([{ type: "emit_error", message: "No tool activity yet." }]);
  });

  test("/details with tool toggles panel", async () => {
    const result = await routeSlashCommand("/details", ctx);
    expect(result.effects).toEqual([{ type: "toggle_details" }]);
  });

  test("/queue resume", async () => {
    const result = await routeSlashCommand("/queue resume", ctx);
    expect(result.effects).toEqual([{ type: "queue_resume" }]);
  });

  test("/queue clear", async () => {
    const result = await routeSlashCommand("/queue clear", ctx);
    expect(result.effects).toEqual([{ type: "queue_clear" }]);
  });

  test("/queue remove with valid index", async () => {
    const result = await routeSlashCommand("/queue remove 2", ctx);
    expect(result.effects).toEqual([{ type: "queue_remove", index: 1 }]);
  });

  test("/queue remove invalid shows usage", async () => {
    const result = await routeSlashCommand("/queue remove", ctx);
    expect(
      result.effects.some((e) => e.type === "emit_error" && e.message.includes("Usage:")),
    ).toBe(true);
  });

  test("/resume emits load_session without id", async () => {
    const result = await routeSlashCommand("/resume", ctx);
    expect(result.effects).toEqual([{ type: "load_session" }]);
  });

  test("/resume with id emits load_session", async () => {
    const result = await routeSlashCommand("/resume abc123", ctx);
    expect(result.effects).toEqual([{ type: "load_session", sessionId: "abc123" }]);
  });
});
