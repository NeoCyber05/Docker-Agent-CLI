import { Readable, Writable } from "node:stream";
import { type Instance, render } from "ink";
import React from "react";
import { PromptInput } from "src/components/PromptInput";
import { afterEach, describe, expect, test, vi } from "vitest";

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

function stripAnsi(value: string): string {
  const ansiPattern = new RegExp(`${String.fromCharCode(27)}\\[[0-9;?]*[ -/]*[@-~]`, "g");
  return value.replace(ansiPattern, "");
}

function renderPrompt(onSubmit = vi.fn()): { app: Instance; stdin: TestStdin; stdout: TestStdout } {
  const stdin = new TestStdin();
  const stdout = new TestStdout();
  const stderr = new TestStdout();
  const app = render(React.createElement(PromptInput, { onSubmit }), {
    stdin: stdin as unknown as NodeJS.ReadStream,
    stdout: stdout as unknown as NodeJS.WriteStream,
    stderr: stderr as unknown as NodeJS.WriteStream,
    debug: true,
    patchConsole: false,
    exitOnCtrlC: false,
  });
  return { app, stdin, stdout };
}

describe("PromptInput slash suggestions", () => {
  const apps: Instance[] = [];

  afterEach(() => {
    for (const app of apps.splice(0)) {
      app.unmount();
      app.cleanup();
    }
    vi.restoreAllMocks();
  });

  test("shows slash command suggestions after typing slash", async () => {
    const rendered = renderPrompt();
    apps.push(rendered.app);
    await new Promise((resolve) => setImmediate(resolve));

    rendered.stdin.push("/");
    rendered.stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));

    const output = stripAnsi(rendered.stdout.output());
    expect(output).toContain("/help");
    expect(output).toContain("/connect");
    expect(output).not.toContain("/provider");
    expect(output).not.toContain("/apikey");
    expect(output).toContain("Tab to complete");
  });

  test("tab completes the selected slash command", async () => {
    const rendered = renderPrompt();
    apps.push(rendered.app);
    await new Promise((resolve) => setImmediate(resolve));

    rendered.stdin.push("/c");
    rendered.stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));
    rendered.stdin.push("\t");
    rendered.stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));

    const output = stripAnsi(rendered.stdout.output());
    expect(output).toContain("/connect");
  });

  test("submits ordinary text with Enter", async () => {
    const onSubmit = vi.fn();
    const rendered = renderPrompt(onSubmit);
    apps.push(rendered.app);
    await new Promise((resolve) => setImmediate(resolve));
    rendered.stdin.push("wait");
    rendered.stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));
    rendered.stdin.push("\r");
    rendered.stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));
    expect(onSubmit).toHaveBeenCalledWith("wait");
  });

  test("submits a paste followed immediately by Enter", async () => {
    const onSubmit = vi.fn();
    const rendered = renderPrompt(onSubmit);
    apps.push(rendered.app);
    await new Promise((resolve) => setImmediate(resolve));
    rendered.stdin.push("wait");
    rendered.stdin.emit("readable");
    rendered.stdin.push("\r");
    rendered.stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));
    expect(onSubmit).toHaveBeenCalledWith("wait");
  });
});
