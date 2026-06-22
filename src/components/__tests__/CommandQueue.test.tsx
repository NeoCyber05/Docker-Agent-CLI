import { Readable, Writable } from "node:stream";
import { type Instance, render } from "ink";
import React from "react";
import { type Command, createDefaultRegistry } from "src/commands/registry";
import { CommandPalette } from "src/components/CommandPalette";
import { QueuePanel } from "src/components/QueuePanel";
import { SLASH_COMMANDS } from "src/slashCommands";
import { afterEach, describe, expect, it, vi } from "vitest";

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

function renderCommandPalette(commands: Command[], onSelect = vi.fn(), onClose = vi.fn()) {
  const stdin = new TestStdin();
  const stdout = new TestStdout();
  const stderr = new TestStdout();
  const app = render(React.createElement(CommandPalette, { commands, onSelect, onClose }), {
    stdin: stdin as unknown as NodeJS.ReadStream,
    stdout: stdout as unknown as NodeJS.WriteStream,
    stderr: stderr as unknown as NodeJS.WriteStream,
    debug: true,
    patchConsole: false,
    exitOnCtrlC: false,
  });
  return { app, stdin, stdout, stderr };
}

function renderQueuePanel(
  queue: string[],
  onRemove = vi.fn(),
  onClear = vi.fn(),
  onResume = vi.fn(),
  onClose = vi.fn(),
) {
  const stdin = new TestStdin();
  const stdout = new TestStdout();
  const stderr = new TestStdout();
  const app = render(React.createElement(QueuePanel, { queue, onRemove, onClear, onResume, onClose }), {
    stdin: stdin as unknown as NodeJS.ReadStream,
    stdout: stdout as unknown as NodeJS.WriteStream,
    stderr: stderr as unknown as NodeJS.WriteStream,
    debug: true,
    patchConsole: false,
    exitOnCtrlC: false,
  });
  return { app, stdin, stdout, stderr };
}

describe("CommandPalette", () => {
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
    vi.restoreAllMocks();
  });

  it("renders commands and selects with Enter", async () => {
    const commands: Command[] = [
      { id: "cancel", title: "Cancel", description: "Cancel current turn", action: vi.fn() },
      { id: "details", title: "Details", description: "Open tool details", action: vi.fn() },
    ];
    const onSelect = vi.fn();
    const { stdout, app } = renderCommandPalette(commands, onSelect);
    apps.push(app);
    await new Promise<void>((resolve) => setImmediate(resolve));
    const text = stripAnsi(stdout.output());
    expect(text).toContain("Cancel");
    expect(text).toContain("Details");
  });

  it("uses the shared slash command catalog", () => {
    const commands = createDefaultRegistry().getAll();
    expect(commands).toHaveLength(SLASH_COMMANDS.length);
    expect(commands.map((command) => command.id)).toEqual(
      expect.arrayContaining(["help", "model", "stacks", "connect"]),
    );
  });
});

describe("QueuePanel", () => {
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
    vi.restoreAllMocks();
  });

  it("renders queue items", async () => {
    const { stdout, app } = renderQueuePanel(["deploy", "status"]);
    apps.push(app);
    await new Promise<void>((resolve) => setImmediate(resolve));
    const text = stripAnsi(stdout.output());
    expect(text).toContain("deploy");
    expect(text).toContain("status");
    expect(text).toContain("Queue (2)");
  });
});
