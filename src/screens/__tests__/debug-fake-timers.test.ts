import { Readable, Writable } from "node:stream";
import { Box, type Instance, Text, render } from "ink";
import React, { useState, useEffect } from "react";
// @ts-expect-error — no @types/react-reconciler; used only for flushSync in tests
import createReconciler from "react-reconciler";
import { afterEach, beforeEach, describe, test, vi } from "vitest";

const SPINNER_FRAMES = ["⠋", "⠙", "⠹"];

type ReconcilerNode = { children: ReconcilerNode[] };

// A minimal reconciler instance used ONLY to access flushSync.
// React's state is global; calling flushSync on any reconciler flushes all pending updates.
const _flushReconciler = createReconciler({
  getRootHostContext: () => ({}),
  prepareForCommit: () => null,
  resetAfterCommit: () => {},
  getChildHostContext: () => ({}),
  shouldSetTextContent: () => false,
  createInstance: (): ReconcilerNode => ({ children: [] }),
  createTextInstance: (text: string) => ({ text }),
  appendInitialChild: (parent: ReconcilerNode, child: ReconcilerNode) =>
    parent.children.push(child),
  appendChild: (parent: ReconcilerNode, child: ReconcilerNode) => parent.children.push(child),
  appendChildToContainer: (parent: ReconcilerNode, child: ReconcilerNode) =>
    parent.children.push(child),
  insertBefore: () => {},
  insertInContainerBefore: () => {},
  removeChild: () => {},
  removeChildFromContainer: () => {},
  prepareUpdate: () => ({}),
  commitUpdate: () => {},
  commitTextUpdate: () => {},
  resetTextContent: () => {},
  clearContainer: () => false,
  getPublicInstance: (i: ReconcilerNode) => i,
  preparePortalMount: () => {},
  finalizeInitialChildren: () => false,
  detachDeletedInstance: () => {},
  isPrimaryRenderer: false,
  supportsMutation: true,
  supportsPersistence: false,
  supportsHydration: false,
  scheduleTimeout: setTimeout,
  cancelTimeout: clearTimeout,
  noTimeout: -1,
  getCurrentEventPriority: () => 0,
  beforeActiveInstanceBlur: () => {},
  afterActiveInstanceBlur: () => {},
  getInstanceFromNode: () => null,
  prepareScopeUpdate: () => {},
  getInstanceFromScope: () => null,
});

function ThinkingIndicator(): React.ReactElement {
  const [frameIndex, setFrameIndex] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      _flushReconciler.batchedUpdates(() => {
        setFrameIndex((i) => (i + 1) % SPINNER_FRAMES.length);
      });
    }, 100);
    return () => clearInterval(id);
  }, []);

  const frame = SPINNER_FRAMES[frameIndex] ?? SPINNER_FRAMES[0];
  return React.createElement(Text, { color: "yellow" as const }, `${frame} Thinking…`);
}

class TestStdout extends Writable {
  columns = 100;
  rows = 24;
  isTTY = true;
  chunks: string[] = [];
  _write(chunk: Buffer | string, _enc: BufferEncoding, cb: (e?: Error) => void) {
    this.chunks.push(String(chunk));
    cb();
  }
  output() {
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

function stripAnsi(s: string) {
  // biome-ignore lint/suspicious/noControlCharactersInRegex: ESC char (\x1b) is intentional for ANSI stripping
  return s.replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, "");
}

describe("debug fake timers", () => {
  const apps: Instance[] = [];

  beforeEach(() => {
    vi.useFakeTimers({
      toFake: ["setTimeout", "setInterval", "clearTimeout", "clearInterval", "Date"],
    });
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    for (const app of apps.splice(0)) {
      try {
        app.unmount();
      } catch {}
      try {
        app.cleanup();
      } catch {}
    }
  });

  test("does the frame change after advanceTimersByTime?", async () => {
    const stdin = new TestStdin();
    const stdout = new TestStdout();
    const stderr = new TestStdout();

    const app = render(
      React.createElement(Box, { paddingLeft: 1 }, React.createElement(ThinkingIndicator)),
      {
        stdin: stdin as unknown as NodeJS.ReadStream,
        stdout: stdout as unknown as NodeJS.WriteStream,
        stderr: stderr as unknown as NodeJS.WriteStream,
        debug: true,
        patchConsole: false,
        exitOnCtrlC: false,
      },
    );
    apps.push(app);

    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    const frame1 = stripAnsi(stdout.output());
    console.log("frame1:", JSON.stringify(frame1));
    console.log("chunks before advance:", stdout.chunks.length);

    vi.advanceTimersByTime(200);

    console.log("chunks after advance:", stdout.chunks.length);

    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    console.log("chunks after flush:", stdout.chunks.length);
    const frame2 = stripAnsi(stdout.output());
    console.log("frame2:", JSON.stringify(frame2));
    console.log("frame1 === frame2:", frame1 === frame2);
  });
});
