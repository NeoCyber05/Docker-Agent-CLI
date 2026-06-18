import { Readable, Writable } from "node:stream";
import { render } from "ink";
import React from "react";
import { PermissionDialog } from "src/components/PermissionDialog";
import { expect, test, vi } from "vitest";

class TestStdout extends Writable {
  columns = 100;
  rows = 24;
  isTTY = true;
  output = "";
  _write(chunk: Buffer | string, _encoding: BufferEncoding, callback: () => void) {
    this.output += String(chunk);
    callback();
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

test("permission summary masks secret-bearing input", async () => {
  const stdout = new TestStdout();
  const stderr = new TestStdout();
  const stdin = new TestStdin();
  const app = render(
    React.createElement(PermissionDialog, {
      tool: "exec_docker",
      input: { args: ["login", "--password", "hunter2"], apiKey: "private-key" },
      onAnswer: vi.fn(),
    }),
    {
      stdout: stdout as unknown as NodeJS.WriteStream,
      stderr: stderr as unknown as NodeJS.WriteStream,
      stdin: stdin as unknown as NodeJS.ReadStream,
      debug: true,
      patchConsole: false,
      exitOnCtrlC: false,
    },
  );
  await new Promise<void>((resolve) => setImmediate(resolve));
  expect(stdout.output).not.toContain("hunter2");
  expect(stdout.output).not.toContain("private-key");
  expect(stdout.output).toContain("Docker: login");
  app.unmount();
  app.cleanup();
});
