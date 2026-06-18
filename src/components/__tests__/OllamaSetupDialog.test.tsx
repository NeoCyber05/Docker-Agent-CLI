import { Readable, Writable } from "node:stream";
import { type Instance, render } from "ink";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OllamaSetupDialog } from "../OllamaSetupDialog";

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

describe("OllamaSetupDialog", () => {
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

  it("shows OLLAMA_HOST and retry hint", async () => {
    const stdin = new TestStdin();
    const stdout = new TestStdout();
    const app = render(
      React.createElement(OllamaSetupDialog, {
        host: "http://localhost:11434",
        onRetry: vi.fn(),
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
    expect(frame).toContain("localhost:11434");
    expect(frame).toContain("ollama serve");
    expect(frame).toContain("OLLAMA_HOST");
    expect(frame).toContain("retry");
  });
});
