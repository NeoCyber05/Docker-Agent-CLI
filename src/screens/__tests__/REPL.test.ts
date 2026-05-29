import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { Readable, Writable } from "node:stream";
import { type Instance, render } from "ink";
import React from "react";
import { renderWelcomeBannerForTerminal } from "src/main";
import { REPL } from "src/screens/REPL";
import { MemoryApiKeyStore } from "src/secrets/apiKeyStore";
import type { ProviderEvent } from "src/services/api/types";
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

function stripAnsi(value: string): string {
  const ansiPattern = new RegExp(`${String.fromCharCode(27)}\\[[0-9;?]*[ -/]*[@-~]`, "g");
  return value.replace(ansiPattern, "");
}

function visibleLineCount(value: string): number {
  return stripAnsi(value)
    .split("\n")
    .filter((line) => line.length > 0).length;
}

function countOccurrences(value: string, needle: string): number {
  return value.split(needle).length - 1;
}

function renderRepl(
  size: { columns: number; rows: number },
  options: {
    debug?: boolean;
    writeWelcome?: boolean;
    provider?: ReturnType<typeof fakeProvider>;
    model?: string;
    apiKeyStore?: MemoryApiKeyStore;
  } = {},
): {
  app: Instance;
  stdin: TestStdin;
  stdout: TestStdout;
  tmp: string;
} {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "repl-ui-"));
  const stdout = new TestStdout(size);
  const stderr = new TestStdout(size);
  const stdin = new TestStdin();
  if (options.writeWelcome) {
    stdout.write(
      renderWelcomeBannerForTerminal({
        provider: "fake",
        version: "0.1.0",
        stdout: stdout as unknown as NodeJS.WriteStream,
      }),
    );
  }
  const app = render(
    React.createElement(REPL, {
      version: "0.1.0",
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

  return { app, stdin, stdout, tmp };
}

async function typeLine(stdin: TestStdin, value: string): Promise<void> {
  stdin.push(value);
  stdin.emit("readable");
  await new Promise((resolve) => setImmediate(resolve));
  stdin.push("\r");
  stdin.emit("readable");
  await new Promise((resolve) => setImmediate(resolve));
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

    expect(output).toContain("docker agent");
    expect(output).toContain("provider: fake");
    expect(output).not.toContain("Welcome back");
    expect(output).not.toContain("Tips for getting started");
    expect(visibleLineCount(output)).toBeLessThanOrEqual(8);
  });

  test("does not attach a global resize clear handler outside Ink", async () => {
    const onSpy = vi.spyOn(process.stdout, "on");
    const clearSpy = vi.spyOn(console, "clear").mockImplementation(() => {});

    const rendered = renderRepl({ columns: 100, rows: 24 }, { debug: false, writeWelcome: true });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    expect(onSpy.mock.calls.some(([event]) => event === "resize")).toBe(false);
    process.stdout.emit("resize");
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(clearSpy).not.toHaveBeenCalled();
  });

  test("does not append duplicate welcome frames when the terminal is resized", async () => {
    const rendered = renderRepl({ columns: 100, rows: 24 }, { debug: false, writeWelcome: true });
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

    const output = stripAnsi(rendered.stdout.output());
    expect(countOccurrences(output, "docker agent")).toBe(1);
    expect(countOccurrences(output, "Tips for getting started")).toBe(1);
  });

  test("slash quit exits through Ink instead of process.exit", async () => {
    const exitSpy = vi.spyOn(process, "exit").mockImplementation(() => {
      throw new Error("process.exit should not be called from REPL");
    });
    const rendered = renderRepl({ columns: 100, rows: 24 });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    const waitForExit = rendered.app.waitUntilExit();
    await new Promise((resolve) => setImmediate(resolve));

    rendered.stdin.push("/quit");
    rendered.stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));
    rendered.stdin.push("\r");
    rendered.stdin.emit("readable");

    await expect(waitForExit).resolves.toBeUndefined();
    expect(exitSpy).not.toHaveBeenCalled();
  });

  test("slash provider updates the visible active provider", async () => {
    const rendered = renderRepl({ columns: 100, rows: 24 });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    await typeLine(rendered.stdin, "/provider openai");

    const output = stripAnsi(rendered.stdout.output());
    expect(output).toContain("provider: openai");
  });

  test("slash model updates the visible active model", async () => {
    const rendered = renderRepl({ columns: 100, rows: 24 });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    await typeLine(rendered.stdin, "/model gpt-4.1-mini");

    const output = stripAnsi(rendered.stdout.output());
    expect(output).toContain("model: gpt-4.1-mini");
  });

  test("slash apikey status reports each provider separately", async () => {
    Reflect.deleteProperty(process.env, "OPENAI_API_KEY");
    Reflect.deleteProperty(process.env, "GEMINI_API_KEY");
    const apiKeyStore = new MemoryApiKeyStore({ openai: "stored-openai-key" });
    const rendered = renderRepl({ columns: 100, rows: 24 }, { apiKeyStore });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    await typeLine(rendered.stdin, "/apikey status");

    const output = stripAnsi(rendered.stdout.output());
    expect(output).toContain("openai: set");
    expect(output).toContain("gemini: unset");
    expect(output).not.toContain("stored-openai-key");
  });

  test("slash apikey set saves a masked key without echoing the value", async () => {
    const apiKeyStore = new MemoryApiKeyStore();
    const rendered = renderRepl({ columns: 100, rows: 24 }, { apiKeyStore });
    apps.push(rendered.app);
    tmpDirs.push(rendered.tmp);
    await new Promise((resolve) => setImmediate(resolve));

    await typeLine(rendered.stdin, "/apikey set openai");
    rendered.stdin.push("sk-persistent-test-key");
    rendered.stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));
    rendered.stdin.push("\r");
    rendered.stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));

    await expect(apiKeyStore.get("openai")).resolves.toBe("sk-persistent-test-key");
    const output = stripAnsi(rendered.stdout.output());
    expect(output).toContain("API key saved for openai");
    expect(output).toContain("**********************");
    expect(output).not.toContain("sk-persistent-test-key");
  });
});
