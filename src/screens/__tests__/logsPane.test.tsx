import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { Readable, Writable } from "node:stream";
import { type Instance, render } from "ink";
import React from "react";
import { REPL } from "src/screens/REPL";
import type { ProviderEvent } from "src/services/api/types";
import { StateStore } from "src/state/StateStore";
import { afterEach, describe, expect, test, vi } from "vitest";
import { MockComposeRunner } from "../../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../../tests/mocks/mockDockerEngine";

class TestStdout extends Writable {
  columns = 100;
  rows = 24;
  isTTY = true;
  private chunks: string[] = [];
  _write(chunk: Buffer | string, _enc: BufferEncoding, cb: (e?: Error) => void) {
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

function fakeProvider(events: ProviderEvent[] = []) {
  return {
    name: "fake",
    stream: async function* () {
      for (const ev of events) yield ev;
    },
  };
}

function renderRepl(runner: MockComposeRunner, tmp: string) {
  const stdout = new TestStdout();
  const stderr = new TestStdout();
  const stdin = new TestStdin();
  const app = render(
    React.createElement(REPL, {
      version: "0.1.0",
      showBanner: false,
      deps: {
        cwd: tmp,
        stateStore: new StateStore(tmp),
        dockerEngine: new MockDockerEngine() as never,
        composeRunner: runner as never,
        provider: fakeProvider() as never,
        providerName: "fake",
      },
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
  return { app, stdin, stdout };
}

async function typeLine(stdin: TestStdin, value: string): Promise<void> {
  stdin.push(value);
  stdin.emit("readable");
  await new Promise((r) => setImmediate(r));
  stdin.push("\r");
  stdin.emit("readable");
  await new Promise((r) => setImmediate(r));
}

describe("REPL /logs pane", () => {
  const apps: Instance[] = [];
  const tmpDirs: string[] = [];

  afterEach(() => {
    for (const app of apps.splice(0)) {
      app.unmount();
      app.cleanup();
    }
    for (const tmp of tmpDirs.splice(0)) fs.rmSync(tmp, { recursive: true, force: true });
    vi.restoreAllMocks();
  });

  function setupStack(tmp: string): void {
    const dir = path.join(tmp, ".docker-agent", "states");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, "web.yaml"), "services: {}\n");
  }

  test("/logs opens a pane, hides the prompt, and renders streamed lines; Esc aborts the follow", async () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "logspane-"));
    tmpDirs.push(tmp);
    setupStack(tmp);

    let aborted = false;
    const runner = new MockComposeRunner(tmp);
    runner.onBoundRunnerCreated = (b) => {
      b.logs = ((
        opts: {
          service?: string;
          tailLines?: number;
          follow?: boolean;
          signal?: AbortSignal;
        } = {},
      ) => {
        // Record the call so we can assert follow/tailLines/signal below.
        b.logsCalls.push(opts);
        return (async function* () {
          yield "live-line-1\n";
          // Wait until aborted, then end the generator cleanly.
          await new Promise<void>((resolve) => {
            if (opts.signal?.aborted) {
              aborted = true;
              resolve();
              return;
            }
            opts.signal?.addEventListener(
              "abort",
              () => {
                aborted = true;
                resolve();
              },
              { once: true },
            );
          });
          return 0;
        })();
      }) as never;
    };

    const { app, stdin, stdout } = renderRepl(runner, tmp);
    apps.push(app);
    await new Promise((r) => setImmediate(r));

    await typeLine(stdin, "/logs web");
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setTimeout(r, 20));

    const out1 = stripAnsi(stdout.output());
    expect(out1).toContain("Live logs: web");
    expect(out1).toContain("live-line-1");
    expect(out1).toContain("Esc to stop");

    // Esc closes the pane and aborts the follow.
    stdin.push("\u001b");
    stdin.emit("readable");
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setTimeout(r, 20));

    expect(aborted).toBe(true);
    // composeRunner.logs was called with follow:true and the abort signal.
    const bound = runner.boundFor("web");
    expect(bound.logsCalls[0]).toMatchObject({ follow: true, tailLines: 50 });
    expect(bound.logsCalls[0]?.signal).toBeInstanceOf(AbortSignal);
  });

  test("/logs on a missing stack prints an inline error and opens no pane", async () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "logspane-"));
    tmpDirs.push(tmp);
    const runner = new MockComposeRunner(tmp);
    const { app, stdin, stdout } = renderRepl(runner, tmp);
    apps.push(app);
    await new Promise((r) => setImmediate(r));

    await typeLine(stdin, "/logs ghost");
    await new Promise((r) => setImmediate(r));

    const out = stripAnsi(stdout.output());
    expect(out.toLowerCase()).toContain("not found");
    expect(out).not.toContain("Esc to stop");
  });
});
