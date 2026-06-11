import { Readable, Writable } from "node:stream";
import { type Instance, render } from "ink";
import React from "react";
import { LogPane, MAX_VISIBLE_LINES } from "src/components/LogPane";
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
  // Ink reads keystrokes via stdin "readable" when raw mode is on.
  press(data: string) {
    this.push(data);
    this.emit("readable");
  }
}

function renderPane(props: React.ComponentProps<typeof LogPane>): {
  text: () => string;
  stdin: TestStdin;
  app: Instance;
} {
  const stdin = new TestStdin();
  const stdout = new TestStdout();
  const stderr = new TestStdout();
  const app = render(React.createElement(LogPane, props), {
    stdin: stdin as unknown as NodeJS.ReadStream,
    stdout: stdout as unknown as NodeJS.WriteStream,
    stderr: stderr as unknown as NodeJS.WriteStream,
    debug: true,
    patchConsole: false,
    exitOnCtrlC: false,
  });
  const stripAnsi = (v: string) =>
    v.replace(new RegExp(`${String.fromCharCode(27)}\\[[0-9;?]*[ -/]*[@-~]`, "g"), "");
  return { text: () => stripAnsi(stdout.output()), stdin, app };
}

describe("LogPane", () => {
  const apps: Instance[] = [];
  afterEach(() => {
    for (const app of apps.splice(0)) {
      try {
        app.unmount();
      } catch {
        /* ignore */
      }
      try {
        app.cleanup();
      } catch {
        /* ignore */
      }
    }
  });

  test("renders the footer hint and stack name", async () => {
    const { text, app } = renderPane({
      stackName: "web",
      lines: ["hello\n"],
      onClose: vi.fn(),
    });
    apps.push(app);
    await new Promise<void>((r) => setImmediate(r));
    expect(text()).toContain("web");
    expect(text()).toContain("Esc to stop");
    expect(text()).toContain("hello");
  });

  test("displays at most MAX_VISIBLE_LINES (ring buffer cap)", async () => {
    const many = Array.from({ length: MAX_VISIBLE_LINES + 50 }, (_, i) => `line-${i}\n`);
    const { text, app } = renderPane({ stackName: "web", lines: many, onClose: vi.fn() });
    apps.push(app);
    await new Promise<void>((r) => setImmediate(r));
    const out = text();
    // Oldest lines are dropped, newest kept.
    expect(out).toContain(`line-${MAX_VISIBLE_LINES + 49}`);
    expect(out).not.toContain("line-0\n");
  });

  test("pressing Esc calls onClose", async () => {
    const onClose = vi.fn();
    const { stdin, app } = renderPane({ stackName: "web", lines: [], onClose });
    apps.push(app);
    await new Promise<void>((r) => setImmediate(r));
    stdin.press("\u001b"); // Esc
    await new Promise<void>((r) => setImmediate(r));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
