/**
 * Bug 5 — Raw-mode teardown during the "thinking" phase freezes the next dialog.
 *
 * Root cause:
 *   Ink reference-counts stdin raw mode by the number of mounted `useInput`
 *   hooks (see node_modules/ink/build/components/App.js -> handleSetRawMode).
 *   When the count drops to 0 Ink calls `stdin.setRawMode(false)` AND removes
 *   the `'readable'` listener that delivers keypresses. While the agent is
 *   streaming, the REPL renders only <ThinkingIndicator/> (no `useInput`), so
 *   the count hits 0 and the listener is torn down. When a dialog such as
 *   <PlanPreview/> mounts afterwards Ink must re-attach the listener; on some
 *   terminals (notably Windows Terminal) that re-attach is unreliable and the
 *   dialog can no longer receive keypresses — it appears "completely frozen".
 *
 * The fix holds a single raw-mode reference for the REPL's whole lifetime so
 * the count never reaches 0 and the `'readable'` listener is never torn down.
 *
 * Observable invariant (deterministic, platform-independent):
 *   Ink only calls the underlying `stdin.setRawMode(...)` at the 0<->1 count
 *   boundary. Therefore, while the app is alive, the real stdin must NEVER be
 *   switched off — i.e. `stdin.setRawMode(false)` must not be called during a
 *   streaming transition.
 *
 * EXPECTED OUTCOME ON UNFIXED CODE: FAIL
 *   The streaming phase drops the count to 0, so `setRawMode(false)` is called.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { Readable, Writable } from "node:stream";
import { type Instance, render } from "ink";
import React from "react";
import { REPL } from "src/screens/REPL";
import { MemoryApiKeyStore } from "src/secrets/apiKeyStore";
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

/**
 * A provider whose stream pauses on `gate` after emitting one text delta, so the
 * REPL commits `streaming = true` (PromptInput unmounts, ThinkingIndicator
 * mounts) and stays there until the test releases the gate.
 */
function gatedProvider(gate: Promise<void>) {
  return {
    name: "fake",
    stream: async function* (): AsyncGenerator<ProviderEvent> {
      yield { type: "text_delta", text: "thinking" };
      await gate;
      yield { type: "message_stop", stopReason: "end_turn" };
    },
  };
}

async function tick(): Promise<void> {
  await new Promise((resolve) => setImmediate(resolve));
}

describe("Bug 5 — stdin raw mode must survive the streaming → dialog transition", () => {
  const apps: Instance[] = [];
  const tmpDirs: string[] = [];

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
    for (const tmp of tmpDirs.splice(0)) {
      fs.rmSync(tmp, { recursive: true, force: true });
    }
    vi.restoreAllMocks();
  });

  test("does not switch stdin out of raw mode while the agent is streaming", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });

    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "bug5-rawmode-"));
    tmpDirs.push(tmp);
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
          composeRunner: new MockComposeRunner(tmp) as never,
          provider: gatedProvider(gate) as never,
          providerName: "fake",
          apiKeyStore: new MemoryApiKeyStore(),
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
    apps.push(app);

    // Initial render: a useInput is mounted, so Ink turns raw mode on once.
    await tick();
    expect(stdin.setRawMode).toHaveBeenCalledWith(true);

    // Submit a prompt → REPL sets streaming = true → PromptInput unmounts and
    // only <ThinkingIndicator/> (no useInput) remains while the provider is
    // parked on the gate.
    stdin.push("hello");
    stdin.emit("readable");
    await tick();
    stdin.push("\r");
    stdin.emit("readable");
    await tick();
    await tick();
    await tick();

    // Invariant: stdin must still be in raw mode. On unfixed code the useInput
    // count dropped to 0, so Ink called setRawMode(false) and removed the
    // 'readable' keypress listener — the teardown that freezes the next dialog.
    const wentOff = stdin.setRawMode.mock.calls.some(([enabled]) => enabled === false);
    expect(
      wentOff,
      "Ink called stdin.setRawMode(false) during streaming — the 'readable' " +
        "keypress listener was torn down and the next dialog will not receive input.",
    ).toBe(false);

    release();
    await tick();
  });
});
