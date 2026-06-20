import { Readable, Writable } from "node:stream";
import { type Instance, render } from "ink";
import React from "react";
import { PromptInput } from "src/components/PromptInput";
import { afterEach, describe, expect, test } from "vitest";

class TestStdout extends Writable {
  columns = 100;
  rows = 24;
  isTTY = true;
  private chunks: string[] = [];
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
  setEncoding = () => this;
  setRawMode = () => this;
  _read() {}
  ref() {
    return this;
  }
  unref() {
    return this;
  }
}

function stripAnsi(value: string): string {
  const pattern = new RegExp(`${String.fromCharCode(27)}\\[[0-9;?]*[ -/]*[@-~]`, "g");
  return value.replace(pattern, "");
}

describe("PromptInput", () => {
  const apps: Instance[] = [];
  afterEach(() => {
    for (const app of apps.splice(0)) {
      try {
        app.unmount();
        app.cleanup();
      } catch {
        /* ignore */
      }
    }
  });

  test("renders input with cursor block", async () => {
    const stdout = new TestStdout();
    const app = render(React.createElement(PromptInput, { onSubmit: () => {} }), {
      stdin: new TestStdin() as unknown as NodeJS.ReadStream,
      stdout: stdout as unknown as NodeJS.WriteStream,
      debug: true,
      patchConsole: false,
      exitOnCtrlC: false,
    });
    apps.push(app);
    await new Promise<void>((resolve) => setImmediate(resolve));
    expect(stripAnsi(stdout.output())).toContain("█");
  });
});
