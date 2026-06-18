import { Readable, Writable } from "node:stream";
import { type Instance, render } from "ink";
import React from "react";
import type { CatalogRow } from "src/services/modelCatalog";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ModelPickerDialog } from "../ModelPickerDialog";

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

const SAMPLE_ROWS: CatalogRow[] = [
  { kind: "header", provider: "gemini", connected: true },
  { kind: "model", provider: "gemini", model: "gemini-2.0-flash" },
  { kind: "model", provider: "gemini", model: "gemini-2.5-pro" },
  { kind: "header", provider: "openai", connected: true },
  { kind: "model", provider: "openai", model: "gpt-4o-mini" },
  { kind: "header", provider: "ollama", connected: false },
  { kind: "connect", provider: "ollama", reason: "ECONNREFUSED" },
];

describe("ModelPickerDialog", () => {
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

  it("shows checkmark on connected provider headers", async () => {
    const stdin = new TestStdin();
    const stdout = new TestStdout();
    const app = render(
      React.createElement(ModelPickerDialog, {
        rows: SAMPLE_ROWS,
        onSelect: vi.fn(),
        onConnectProvider: vi.fn(),
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
    expect(frame).toContain("Gemini");
    expect(frame).toContain("OpenAI");
    expect(frame).toContain("✓");
    expect(frame).toContain("Ollama");
  });

  it('renders "Not connected" on connect rows', async () => {
    const stdin = new TestStdin();
    const stdout = new TestStdout();
    const app = render(
      React.createElement(ModelPickerDialog, {
        rows: SAMPLE_ROWS,
        onSelect: vi.fn(),
        onConnectProvider: vi.fn(),
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
    expect(frame).toContain("Not connected");
  });

  it("renders model names", async () => {
    const stdin = new TestStdin();
    const stdout = new TestStdout();
    const app = render(
      React.createElement(ModelPickerDialog, {
        rows: SAMPLE_ROWS,
        current: { provider: "gemini", model: "gemini-2.0-flash" },
        onSelect: vi.fn(),
        onConnectProvider: vi.fn(),
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
    expect(frame).toContain("gemini-2.0-flash");
    expect(frame).toContain("gemini-2.5-pro");
    expect(frame).toContain("gpt-4o-mini");
    expect(frame).toContain("(current)");
  });
});
