import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { Readable, Writable } from "node:stream";
import { type Instance, render } from "ink";
import React from "react";
import { renderWelcomeBannerForTerminal } from "src/main";
import { REPL } from "src/screens/REPL";
import { MemoryApiKeyStore } from "src/secrets/apiKeyStore";
import * as api from "src/services/api";
import type { ProviderEvent } from "src/services/api/types";
import { formatSlashHelp } from "src/slashCommands";
import type { SessionRecord } from "src/state/SessionStore";
import { StateStore } from "src/state/StateStore";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { MockComposeRunner } from "../../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../../tests/mocks/mockDockerEngine";

class TestStdout extends Writable {
  columns: number;
  rows: number;
  isTTY = true;
  private chunks: string[] = [];

  constructor({ columns, rows }: { columns: number; rows: number }) {
    super();
    this.columns = columns;
    this.rows = rows;
  }

  _write(chunk: Buffer | string, _encoding: BufferEncoding, callback: (error?: Error) => void) {
    this.chunks.push(String(chunk));
    callback();
  }

  output(): string {
    return this.chunks.join("");
  }
}

class TestStdin extends Readable {
  isTTY = true;
  setEncoding = vi.fn();
  setRawMode = vi.fn();

  _read() {}

  ref() {
    return this;
  }

  unref() {
    return this;
  }
}

function fakeProvider(events: ProviderEvent[] = []) {
  return {
    name: "fake",
    stream: async function* () {
      for (const ev of events) yield ev;
    },
  };
}

function trackingProvider(): {
  provider: { name: string; stream: (params: unknown) => AsyncGenerator<ProviderEvent> };
  queriedWith: string[];
} {
  const queriedWith: string[] = [];
  const provider = {
    name: "fake",
    stream: async function* (params: unknown) {
      const msgs =
        typeof params === "object" && params !== null && "messages" in params
          ? ((params as { messages: Array<{ role: string; content: unknown }> }).messages ?? [])
          : [];
      const last = msgs[msgs.length - 1];
      if (last?.role === "user" && typeof last.content === "string") {
        queriedWith.push(last.content);
      }
      yield { type: "message_stop" as const, stopReason: "end_turn" as const };
    },
  };
  return { provider, queriedWith };
}

function stripAnsi(value: string): string {
  const ansiPattern = new RegExp(`${String.fromCharCode(27)}\\[[0-9;?]*[ -/]*[@-~]`, "g");
  return value.replace(ansiPattern, "");
}

function visibleLineCount(value: string): number {
  return stripAnsi(value)
    .split("\n")
    .filter((line) => line.length > 0).length;
}

function maxVisibleLineWidth(value: string): number {
  return Math.max(
    0,
    ...stripAnsi(value)
      .split("\n")
      .map((line) => line.length),
  );
}

function countOccurrences(value: string, needle: string): number {
  return value.split(needle).length - 1;
}

function renderTerminal(raw: string): string {
  const lines: string[] = [];
  let y = 0;
  let x = 0;
  let i = 0;
  while (i < raw.length) {
    if (raw.startsWith("\u001b[", i)) {
      i += 2;
      let seq = "";
      while (i < raw.length && !/[a-zA-Z]/.test(raw[i] as string)) {
        seq += raw[i];
        i++;
      }
      const cmd = raw[i];
      i++;
      if (cmd === "A") {
        y = Math.max(0, y - (seq ? Number.parseInt(seq, 10) : 1));
      } else if (cmd === "H" || cmd === "f") {
        if (seq) {
          const parts = seq.split(";");
          y = Math.max(0, parts[0] ? Number.parseInt(parts[0], 10) - 1 : 0);
          x = Math.max(0, parts[1] ? Number.parseInt(parts[1], 10) - 1 : 0);
        } else {
          y = 0;
          x = 0;
        }
      } else if (cmd === "K") {
        if (seq === "2") lines[y] = "";
      } else if (cmd === "G") {
        x = 0;
      }
    } else if (raw[i] === "\n") {
      y++;
      x = 0;
      i++;
    } else if (raw[i] === "\r") {
      x = 0;
      i++;
    } else {
      if (!lines[y]) lines[y] = "";
      const line = lines[y] as string;
      if (x > line.length) {
        lines[y] = line + " ".repeat(x - line.length) + raw[i];
      } else {
        lines[y] = line.slice(0, x) + raw[i] + line.slice(x + 1);
      }
      x++;
      i++;
    }
  }
  return stripAnsi(lines.filter((l) => l !== undefined).join("\n"));
}

function renderRepl(
  size: { columns: number; rows: number },
  options: {
    debug?: boolean;
    showBanner?: boolean;
    provider?: ReturnType<typeof fakeProvider>;
    model?: string;
    apiKeyStore?: MemoryApiKeyStore;
    resumedRecord?: SessionRecord;
  } = {},
): {
  app: Instance;
  stdin: TestStdin;
  stdout: TestStdout;
  stderr: TestStdout;
  tmp: string;
} {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "repl-ui-"));
  fs.writeFileSync(path.join(tmp, "project-policies.yaml"), "project: {}");
  const stdout = new TestStdout(size);
  const stderr = new TestStdout(size);
  const stdin = new TestStdin();
  const app = render(
    React.createElement(REPL, {
      version: "0.1.0",
      showBanner: options.showBanner ?? false,
      ...(options.resumedRecord ? { resumedRecord: options.resumedRecord } : {}),
      deps: {
        cwd: tmp,
        stateStore: new StateStore(tmp),
        dockerEngine: new MockDockerEngine() as never,
        composeRunner: new MockComposeRunner(tmp) as never,
        provider: (options.provider ?? fakeProvider()) as never,
        providerName: "fake",
        ...(options.model ? { model: options.model } : {}),
        ...(options.apiKeyStore ? { apiKeyStore: options.apiKeyStore } : {}),
      },
    }),
    {
      stdout: stdout as unknown as NodeJS.WriteStream,
      stderr: stderr as unknown as NodeJS.WriteStream,
      stdin: stdin as unknown as NodeJS.ReadStream,
      debug: options.debug ?? true,
      patchConsole: false,
      exitOnCtrlC: false,
    },
  );

  return { app, stdin, stdout, stderr, tmp };
}

async function typeLine(stdin: TestStdin, value: string): Promise<void> {
  stdin.push(value);
  stdin.emit("readable");
  await new Promise((resolve) => setImmediate(resolve));
  stdin.push("\r");
  stdin.emit("readable");
  await new Promise((resolve) => setImmediate(resolve));
}

async function waitUntil(predicate: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 50; attempt++) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error("condition was not reached");
}

describe("REPL terminal rendering", () => {
  const apps: Instance[] = [];
  const tmpDirs: string[] = [];
  let originalEnv: NodeJS.ProcessEnv;

  beforeEach(() => {
    originalEnv = { ...process.env };
  });

  afterEach(() => {
    process.env = originalEnv;
    for (const app of apps.splice(0)) {
      app.unmount();
      app.cleanup();
    }
    for (const tmp of tmpDirs.splice(0)) {
      fs.rmSync(tmp, { recursive: true, force: true });
    }
    vi.restoreAllMocks();
  });

  test("uses a compact startup banner in a short terminal", () => {
    const stdout = new TestStdout({ columns: 60, rows: 8 });
    const output = stripAnsi(
      renderWelcomeBannerForTerminal({
        provider: "fake",
        version: "0.1.0",
        stdout: stdout as unknown as NodeJS.WriteStream,
      }),
    );

    expect(output).toContain("docker-agent");
    expect(output).toContain("v0.1.0");
    expect(output).not.toContain("provider:");
    expect(output).not.toContain("Welcome back");
    expect(output).not.toContain("Tips for getting started");
    expect(visibleLineCount(output)).toBeLessThanOrEqual(8);
  });

  test("keeps startup banner lines narrower than the terminal to avoid resize autowrap", () => {
    const stdout = new TestStdout({ columns: 100, rows: 24 });
    const output = renderWelcomeBannerForTerminal({
      provider: "fake",
      version: "0.1.0",
      stdout: stdout as unknown as NodeJS.WriteStream,
    });

    expect(maxVisibleLineWidth(output)).toBeLessThan(stdout.columns);
  });

  test("keeps interactive frame lines narrower than the terminal to avoid resize autowrap", async () => {
    const rendered = renderRepl({ columns: 100, rows: 24 });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    expect(maxVisibleLineWidth(rendered.stdout.output())).toBeLessThan(rendered.stdout.columns);
  });

  test("does not attach a global resize clear handler outside Ink", async () => {
    const onSpy = vi.spyOn(process.stdout, "on");
    const clearSpy = vi.spyOn(console, "clear").mockImplementation(() => {});

    const rendered = renderRepl({ columns: 100, rows: 24 }, { debug: false, showBanner: true });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    expect(onSpy.mock.calls.some(([event]) => event === "resize")).toBe(false);
    process.stdout.emit("resize");
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(clearSpy).not.toHaveBeenCalled();
  });

  test("does not append duplicate welcome frames when the terminal is resized", async () => {
    const rendered = renderRepl({ columns: 100, rows: 24 }, { debug: false, showBanner: true });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    rendered.stdout.columns = 92;
    rendered.stdout.rows = 22;
    rendered.stdout.emit("resize");
    await new Promise((resolve) => setImmediate(resolve));
    rendered.stdout.columns = 100;
    rendered.stdout.rows = 24;
    rendered.stdout.emit("resize");
    await new Promise((resolve) => setImmediate(resolve));

    const output = renderTerminal(rendered.stdout.output());
    expect(countOccurrences(output, "Docker Agent CLI")).toBe(1);
    expect(countOccurrences(output, "Tips for getting started")).toBe(1);
  });

  test("slash exit exits through Ink instead of process.exit", async () => {
    const exitSpy = vi.spyOn(process, "exit").mockImplementation(() => {
      throw new Error("process.exit should not be called from REPL");
    });
    const rendered = renderRepl({ columns: 100, rows: 24 });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    const waitForExit = rendered.app.waitUntilExit();
    await new Promise((resolve) => setImmediate(resolve));

    rendered.stdin.push("/exit");
    rendered.stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));
    rendered.stdin.push("\r");
    rendered.stdin.emit("readable");

    await expect(waitForExit).resolves.toBeUndefined();
    expect(exitSpy).not.toHaveBeenCalled();
  });

  test("formatSlashHelp does not list removed provider commands", () => {
    expect(formatSlashHelp()).not.toContain("/provider");
    expect(formatSlashHelp()).not.toContain("/apikey");
    expect(formatSlashHelp()).toContain("/connect");
  });

  test("/connect opens provider connect dialog", async () => {
    vi.spyOn(api, "resolveProviderForRequest").mockImplementation(
      (name) =>
        ({
          name,
          stream: async function* () {},
          listModels: vi.fn().mockRejectedValue(new Error("ECONNREFUSED")),
        }) as never,
    );

    const rendered = renderRepl({ columns: 100, rows: 24 });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    await typeLine(rendered.stdin, "/connect");
    await waitUntil(() => stripAnsi(rendered.stdout.output()).includes("Popular"));

    const output = stripAnsi(rendered.stdout.output());
    expect(output).toContain("Connect a provider");
    expect(output).toContain("Popular");
  });

  test("/model without args shows grouped model picker for connected providers", async () => {
    const openaiProvider = {
      name: "openai",
      stream: async function* () {},
      listModels: vi.fn().mockResolvedValue(["gpt-4o-mini", "gpt-4.1-mini"]),
    };
    vi.spyOn(api, "resolveProviderForRequest").mockImplementation((name) => {
      if (name === "openai") return openaiProvider as never;
      return fakeProvider() as never;
    });
    process.env.OPENAI_API_KEY = "test-key";

    const rendered = renderRepl({ columns: 100, rows: 24 });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    await typeLine(rendered.stdin, "/model");
    await waitUntil(() => stripAnsi(rendered.stdout.output()).includes("Select model"));

    const output = stripAnsi(rendered.stdout.output());
    expect(output).toContain("Select model");
    expect(output).toContain("OpenAI");
    expect(output).toContain("gpt-4o-mini");
    expect(openaiProvider.listModels).toHaveBeenCalled();
  });

  test("slash model with provider prefix updates header provider and model", async () => {
    const rendered = renderRepl({ columns: 100, rows: 24 });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    await typeLine(rendered.stdin, "/model openai/gpt-4.1-mini");

    const output = stripAnsi(rendered.stdout.output());
    expect(output).toContain("provider: openai");
    expect(output).toContain("model: gpt-4.1-mini");
    expect(output).toContain("Model set to gpt-4.1-mini (openai)");
  });

  test("/connect shows API key source for connected providers", async () => {
    Reflect.deleteProperty(process.env, "OPENAI_API_KEY");
    Reflect.deleteProperty(process.env, "GEMINI_API_KEY");
    vi.spyOn(api, "resolveProviderForRequest").mockImplementation(
      (name) =>
        ({
          name,
          stream: async function* () {},
          listModels: vi.fn().mockRejectedValue(new Error("ECONNREFUSED")),
        }) as never,
    );
    const apiKeyStore = new MemoryApiKeyStore({ openai: "stored-openai-key" });
    const rendered = renderRepl({ columns: 100, rows: 24 }, { apiKeyStore });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    await typeLine(rendered.stdin, "/connect");
    await waitUntil(() => stripAnsi(rendered.stdout.output()).includes("Popular"));

    const output = stripAnsi(rendered.stdout.output());
    expect(output).toContain("Connect a provider");
    expect(output).toContain("saved");
    expect(output).not.toContain("stored-openai-key");
  });

  test("/connect saves API key via provider dialog without echoing the value", async () => {
    Reflect.deleteProperty(process.env, "OPENAI_API_KEY");
    Reflect.deleteProperty(process.env, "GEMINI_API_KEY");
    vi.spyOn(api, "resolveProviderForRequest").mockImplementation(
      (name) =>
        ({
          name,
          stream: async function* () {},
          listModels: vi.fn().mockRejectedValue(new Error("ECONNREFUSED")),
        }) as never,
    );
    const apiKeyStore = new MemoryApiKeyStore();
    const rendered = renderRepl({ columns: 100, rows: 24 }, { apiKeyStore });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    await typeLine(rendered.stdin, "/connect");
    await waitUntil(() => stripAnsi(rendered.stdout.output()).includes("Popular"));
    rendered.stdin.push("\r");
    rendered.stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));

    rendered.stdin.push("gemini-persistent-test-key");
    rendered.stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));
    rendered.stdin.push("\r");
    rendered.stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));

    await expect(apiKeyStore.get("gemini")).resolves.toBe("gemini-persistent-test-key");
    const output = stripAnsi(rendered.stdout.output());
    expect(output).toContain("API key saved for gemini");
    expect(output).toContain("************************");
    expect(output).not.toContain("gemini-persistent-test-key");
  });

  test("hydrates resumed messages including completed tool activity", async () => {
    const resumedRecord: SessionRecord = {
      schemaVersion: 1,
      id: "session-1",
      createdAt: "2026-01-01T00:00:00.000Z",
      updatedAt: "2026-01-01T00:00:01.000Z",
      cwd: "D:/tmp",
      provider: "fake",
      firstPrompt: "show stacks",
      stackNames: [],
      messages: [
        { role: "user", content: "show stacks" },
        {
          role: "assistant",
          content: [
            { type: "text", text: "Checking Docker." },
            { type: "tool_use", id: "tool-1", name: "list_stacks", input: {} },
          ],
        },
        { role: "tool", toolUseId: "tool-1", content: '{"stacks":[]}', isError: false },
      ],
    };
    const rendered = renderRepl({ columns: 100, rows: 24 }, { resumedRecord });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    const output = stripAnsi(rendered.stdout.output());
    expect(output).toContain("show stacks");
    expect(output).toContain("Checking Docker.");
    expect(output).toContain("List stacks");
    expect(output).toContain("completed");
  });

  test("Ctrl+C aborts the active provider stream", async () => {
    let capturedSignal: AbortSignal | undefined;
    const provider = {
      name: "waiting",
      stream: async function* (params: { signal?: AbortSignal }) {
        capturedSignal = params.signal;
        await new Promise<void>((resolve) => {
          if (params.signal?.aborted) resolve();
          else params.signal?.addEventListener("abort", () => resolve(), { once: true });
        });
      },
    };
    const rendered = renderRepl({ columns: 100, rows: 24 }, { provider: provider as never });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await typeLine(rendered.stdin, "wait");
    await waitUntil(() => capturedSignal !== undefined);
    expect(capturedSignal?.aborted).toBe(false);

    rendered.stdin.push("\u0003");
    rendered.stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));

    expect(capturedSignal?.aborted).toBe(true);
  });

  test("provider error pauses queued turns until explicit resume", async () => {
    let releaseFirst: (() => void) | undefined;
    let calls = 0;
    const provider = {
      name: "delayed-error",
      stream: async function* () {
        calls++;
        if (calls === 1) {
          await new Promise<void>((resolve) => {
            releaseFirst = resolve;
          });
          yield { type: "error", error: new Error("provider failed") } as const;
          return;
        }
        yield { type: "message_stop", stopReason: "end_turn" } as const;
      },
    };
    const rendered = renderRepl({ columns: 100, rows: 24 }, { provider: provider as never });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await typeLine(rendered.stdin, "first");
    await waitUntil(() => calls === 1);
    await typeLine(rendered.stdin, "second");
    releaseFirst?.();
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));

    expect(calls).toBe(1);
    expect(stripAnsi(rendered.stdout.output())).toContain("Queue paused");
  });
});

describe("REPL slash command direct dispatch", () => {
  const apps: Instance[] = [];
  const tmpDirs: string[] = [];

  afterEach(() => {
    for (const app of apps.splice(0)) {
      app.unmount();
      app.cleanup();
    }
    for (const tmp of tmpDirs.splice(0)) {
      fs.rmSync(tmp, { recursive: true, force: true });
    }
    vi.restoreAllMocks();
  });

  test("/stacks does not query the LLM and shows a table", async () => {
    const { provider, queriedWith } = trackingProvider();
    const rendered = renderRepl({ columns: 100, rows: 24 }, { provider: provider as never });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    await typeLine(rendered.stdin, "/stacks");

    const output = stripAnsi(rendered.stdout.output());
    expect(output).toContain("Managed stacks");
    expect(output).toContain("No stacks defined");
    expect(queriedWith).toHaveLength(0);
  });

  test("/yaml does not query the LLM and shows redacted stack YAML", async () => {
    const { provider, queriedWith } = trackingProvider();
    const rendered = renderRepl({ columns: 100, rows: 24 }, { provider: provider as never });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);

    fs.mkdirSync(path.join(rendered.tmp, "states"), { recursive: true });
    fs.writeFileSync(
      path.join(rendered.tmp, "states", "webapp.yaml"),
      `x-docker-agent:\n  name: webapp\n  createdAt: "2026-05-26T00:00:00Z"\n  lastApplied: null\n  intent: test\n  provider: gemini\n  generatedBy: test\n  envFileSources: {}\nservices:\n  web:\n    image: nginx:1.27-alpine\n    environment:\n      POSTGRES_PASSWORD: hidden\n      PORT: "8080"\n`,
    );

    await new Promise((resolve) => setImmediate(resolve));
    await typeLine(rendered.stdin, "/yaml webapp");

    const output = stripAnsi(rendered.stdout.output());
    expect(output).toContain("POSTGRES_PASSWORD");
    expect(output).toContain("***");
    expect(output).not.toContain("hidden");
    expect(queriedWith).toHaveLength(0);
  });

  test("missing slash args return usage errors without querying the LLM", async () => {
    const cases = ["/yaml", "/status", "/destroy", "/secrets list", "/secrets rotate mystack"];
    for (const cmd of cases) {
      const { provider, queriedWith } = trackingProvider();
      const rendered = renderRepl({ columns: 100, rows: 24 }, { provider: provider as never });
      apps.push(rendered.app);
      tmpDirs.push(rendered.tmp);
      await new Promise((resolve) => setImmediate(resolve));

      await typeLine(rendered.stdin, cmd);

      expect(queriedWith, `Command "${cmd}" should not query the LLM`).toHaveLength(0);
      expect(stripAnsi(rendered.stdout.output())).toMatch(/Usage:/);
    }
  });

  test("/destroy all is case-insensitive for the all keyword", async () => {
    const { provider, queriedWith } = trackingProvider();
    const rendered = renderRepl({ columns: 100, rows: 24 }, { provider: provider as never });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    await typeLine(rendered.stdin, "/destroy ALL");

    expect(queriedWith).toHaveLength(0);
    expect(stripAnsi(rendered.stdout.output())).toContain("DESTROY ALL");
  });

  test("/destroy <stack> does not query the LLM and requests permission", async () => {
    const { provider, queriedWith } = trackingProvider();
    const rendered = renderRepl({ columns: 100, rows: 24 }, { provider: provider as never });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    await typeLine(rendered.stdin, "/destroy webapp");

    expect(queriedWith).toHaveLength(0);
    expect(stripAnsi(rendered.stdout.output())).toContain("Destroy stack: webapp");
  });

  test("unknown slash command does not query the LLM", async () => {
    const { provider, queriedWith } = trackingProvider();
    const rendered = renderRepl({ columns: 100, rows: 24 }, { provider: provider as never });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    await typeLine(rendered.stdin, "/not-a-command");

    expect(queriedWith).toHaveLength(0);
    expect(stripAnsi(rendered.stdout.output())).toContain("Unknown slash command");
  });
});
