import { Readable, Writable } from "node:stream";
import { type Instance, render } from "ink";
import React from "react";
import { ActivityTimeline } from "src/components/ActivityTimeline";
import type { ActivityItem } from "src/ui/activity";
import { afterEach, describe, expect, it } from "vitest";

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

function renderTimeline(items: ActivityItem[], activeId?: string | null) {
  const stdin = new TestStdin();
  const stdout = new TestStdout();
  const stderr = new TestStdout();
  const app = render(
    React.createElement(ActivityTimeline, { items, activeToolActivityId: activeId ?? null }),
    {
      stdin: stdin as unknown as NodeJS.ReadStream,
      stdout: stdout as unknown as NodeJS.WriteStream,
      stderr: stderr as unknown as NodeJS.WriteStream,
      debug: true,
      patchConsole: false,
      exitOnCtrlC: false,
    },
  );
  return { app, stdout, stderr };
}

describe("ActivityTimeline", () => {
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

  it("shows running symbol for active tool", async () => {
    const items: ActivityItem[] = [
      {
        id: "t1",
        type: "tool",
        name: "list_stacks",
        title: "List stacks",
        summary: "List all stacks",
        status: "running",
        progressMsgs: ["Listing..."],
        detailLines: [],
        startTime: Date.now() - 1000,
      },
    ];
    const { stdout, app } = renderTimeline(items, "t1");
    apps.push(app);
    await new Promise<void>((resolve) => setImmediate(resolve));
    const text = stripAnsi(stdout.output());
    expect(text).toContain("●");
    expect(text).toContain("List stacks");
    expect(text).toContain("Listing...");
  });

  it("shows completed symbol", async () => {
    const items: ActivityItem[] = [
      {
        id: "t1",
        type: "tool",
        name: "list_stacks",
        title: "List stacks",
        summary: "List all stacks",
        status: "completed",
        progressMsgs: [],
        detailLines: ["stacks: [1 items]"],
        startTime: Date.now() - 5000,
        endTime: Date.now() - 1000,
      },
    ];
    const { stdout, app } = renderTimeline(items, null);
    apps.push(app);
    await new Promise<void>((resolve) => setImmediate(resolve));
    const text = stripAnsi(stdout.output());
    expect(text).toContain("✓");
  });

  it("shows failed symbol", async () => {
    const items: ActivityItem[] = [
      {
        id: "t1",
        type: "tool",
        name: "exec_docker",
        title: "Docker: ps",
        summary: "Run docker ps",
        status: "failed",
        progressMsgs: [],
        detailLines: ["Error: exit 1"],
        startTime: Date.now() - 2000,
        endTime: Date.now(),
      },
    ];
    const { stdout, app } = renderTimeline(items, null);
    apps.push(app);
    await new Promise<void>((resolve) => setImmediate(resolve));
    const text = stripAnsi(stdout.output());
    expect(text).toContain("!");
  });

  it("shows cancelled symbol", async () => {
    const items: ActivityItem[] = [
      {
        id: "t1",
        type: "tool",
        name: "pull_image",
        title: "Pull image: nginx",
        summary: "Validate and pull nginx",
        status: "cancelled",
        progressMsgs: ["Pulling..."],
        detailLines: [],
        startTime: Date.now() - 3000,
        endTime: Date.now(),
      },
    ];
    const { stdout, app } = renderTimeline(items, null);
    apps.push(app);
    await new Promise<void>((resolve) => setImmediate(resolve));
    const text = stripAnsi(stdout.output());
    expect(text).toContain("×");
  });

  it("shows duration for completed tool", async () => {
    const start = Date.now() - 5000;
    const end = Date.now() - 1000;
    const items: ActivityItem[] = [
      {
        id: "t1",
        type: "tool",
        name: "list_stacks",
        title: "List stacks",
        summary: "List all stacks",
        status: "completed",
        progressMsgs: [],
        detailLines: [],
        startTime: start,
        endTime: end,
      },
    ];
    const { stdout, app } = renderTimeline(items, null);
    apps.push(app);
    await new Promise<void>((resolve) => setImmediate(resolve));
    const text = stripAnsi(stdout.output());
    expect(text).toMatch(/\d+\.?\d*s/);
  });

  it("renders user and assistant text", async () => {
    const items: ActivityItem[] = [
      { id: "u1", type: "text", role: "user", text: "deploy" },
      { id: "a1", type: "text", role: "assistant", text: "OK" },
    ];
    const { stdout, app } = renderTimeline(items, null);
    apps.push(app);
    await new Promise<void>((resolve) => setImmediate(resolve));
    const text = stripAnsi(stdout.output());
    expect(text).toContain("deploy");
    expect(text).toContain("OK");
  });

  it("keeps the current assistant response live while text streams", async () => {
    const initial: ActivityItem[] = [
      { id: "u1", type: "text", role: "user", text: "deploy" },
      { id: "a1", type: "text", role: "assistant", text: "Hel" },
    ];
    const { app, stdout } = renderTimeline(initial, null);
    apps.push(app);
    await new Promise<void>((resolve) => setImmediate(resolve));

    app.rerender(
      React.createElement(ActivityTimeline, {
        items: [initial[0] as ActivityItem, { ...initial[1], text: "Hello" } as ActivityItem],
        activeToolActivityId: null,
      }),
    );
    await new Promise<void>((resolve) => setImmediate(resolve));

    expect(stripAnsi(stdout.output())).toContain("Hello");
  });

  it("bounds progress to last 3 messages", async () => {
    const items: ActivityItem[] = [
      {
        id: "t1",
        type: "tool",
        name: "pull_image",
        title: "Pull image: nginx",
        summary: "Validate and pull nginx",
        status: "running",
        progressMsgs: ["step 1", "step 2", "step 3", "step 4", "step 5"],
        detailLines: [],
        startTime: Date.now(),
      },
    ];
    const { stdout, app } = renderTimeline(items, "t1");
    apps.push(app);
    await new Promise<void>((resolve) => setImmediate(resolve));
    const text = stripAnsi(stdout.output());
    expect(text).toContain("step 3");
    expect(text).toContain("step 4");
    expect(text).toContain("step 5");
    expect(text).not.toContain("step 1");
    expect(text).not.toContain("step 2");
  });
});
