import { Readable, Writable } from "node:stream";
import { type Instance, render } from "ink";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProviderConnectDialog } from "../ProviderConnectDialog";

class TestStdout extends Writable {
  columns = 100;
  rows = 24;
  isTTY = true;
  private chunks: string[] = [];
  _write(chunk: Buffer | string, _e: BufferEncoding, cb: (e?: Error) => void) {
    this.chunks.push(String(chunk));
    cb();
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

function stripAnsi(v: string): string {
  return v.replace(new RegExp(`${String.fromCharCode(27)}\\[[0-9;?]*[ -/]*[@-~]`, "g"), "");
}

describe("ProviderConnectDialog", () => {
  const apps: Instance[] = [];
  afterEach(() => {
    for (const a of apps.splice(0)) {
      try {
        a.unmount();
        a.cleanup();
      } catch {
        /* ignore */
      }
    }
  });

  it("renders opencode-style title and categories", async () => {
    const stdin = new TestStdin();
    const stdout = new TestStdout();
    const app = render(
      React.createElement(ProviderConnectDialog, {
        statuses: [
          { provider: "gemini", connected: false, reason: "API key not set" },
          { provider: "openai", connected: true },
          { provider: "ollama", connected: false, reason: "ECONNREFUSED" },
        ],
        onSelect: vi.fn(),
        onCancel: vi.fn(),
      }),
      {
        stdout: stdout as unknown as NodeJS.WriteStream,
        stdin: stdin as unknown as NodeJS.ReadStream,
        debug: true,
        patchConsole: false,
        exitOnCtrlC: false,
      },
    );
    apps.push(app);
    await new Promise((r) => setImmediate(r));

    const frame = stripAnsi(stdout.output());
    expect(frame).toContain("Connect a provider");
    expect(frame).toContain("Popular");
    expect(frame).toContain("Providers");
    expect(frame).toContain("Gemini");
    expect(frame).toContain("(API key)");
    expect(frame).toContain("Ollama");
    expect(frame).toContain("(local)");
  });

  it("shows API key source when connected via env or saved store", async () => {
    const stdin = new TestStdin();
    const stdout = new TestStdout();
    const app = render(
      React.createElement(ProviderConnectDialog, {
        statuses: [
          { provider: "openai", connected: true },
          { provider: "gemini", connected: false, reason: "API key not set" },
        ],
        apiKeyStatuses: [
          { provider: "openai", state: "set", source: "saved" },
          { provider: "gemini", state: "unset" },
        ],
        onSelect: vi.fn(),
        onCancel: vi.fn(),
      }),
      {
        stdout: stdout as unknown as NodeJS.WriteStream,
        stdin: stdin as unknown as NodeJS.ReadStream,
        debug: true,
        patchConsole: false,
        exitOnCtrlC: false,
      },
    );
    apps.push(app);
    await new Promise((r) => setImmediate(r));

    const frame = stripAnsi(stdout.output());
    expect(frame).toContain("saved");
  });

  it("shows green checkmark gutter for connected providers", async () => {
    const stdin = new TestStdin();
    const stdout = new TestStdout();
    const app = render(
      React.createElement(ProviderConnectDialog, {
        statuses: [{ provider: "openai", connected: true }],
        onSelect: vi.fn(),
        onCancel: vi.fn(),
      }),
      {
        stdout: stdout as unknown as NodeJS.WriteStream,
        stdin: stdin as unknown as NodeJS.ReadStream,
        debug: true,
        patchConsole: false,
        exitOnCtrlC: false,
      },
    );
    apps.push(app);
    await new Promise((r) => setImmediate(r));

    const frame = stripAnsi(stdout.output());
    expect(frame).toContain("✓");
    expect(frame).toContain("OpenAI");
  });
});
