import { Readable, Writable } from "node:stream";
import { type Instance, render } from "ink";
import React from "react";
import { PlanPreview } from "src/components/PlanPreview";
import type { StackDiff } from "src/types/stack";
import { afterEach, describe, expect, test, vi } from "vitest";

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

function lastRenderedFrame(output: string): string {
  const frameBoundary = new RegExp(`${String.fromCharCode(27)}\\[(?:2J|\\d+;\\d+H|\\d+H|H)`, "g");
  let lastIndex = 0;
  let match = frameBoundary.exec(output);
  while (match !== null) {
    lastIndex = match.index;
    match = frameBoundary.exec(output);
  }
  return stripAnsi(output.slice(lastIndex));
}

const diff: StackDiff = { stackName: "web", status: "missing", serviceDiffs: [] };

describe("PlanPreview", () => {
  test("renders plan preview without crashing", async () => {
    const stdout = new TestStdout();
    const app = render(
      React.createElement(PlanPreview, {
        composeYaml: "version: '3'\nservices:\n  web:\n    image: nginx",
        diff: { stackName: "test", status: "missing", serviceDiffs: [] },
        onAnswer: () => {},
      }),
      {
        stdout: stdout as unknown as NodeJS.WriteStream,
        stdin: new TestStdin() as unknown as NodeJS.ReadStream,
        debug: true,
        patchConsole: false,
        exitOnCtrlC: false,
      },
    );
    await new Promise((r) => setImmediate(r));
    const output = stripAnsi(stdout.output());
    expect(output).toContain("test");
    expect(output).toContain("YAML");
    app.unmount();
    app.cleanup();
  });

  test("hides x-docker-agent metadata when YAML is expanded", async () => {
    const stdin = new TestStdin();
    const stdout = new TestStdout();
    const composeYaml = [
      "x-docker-agent:",
      "  name: redis-cache",
      "  createdAt: 2026-06-23T06:11:12.361Z",
      "  lastApplied: 2026-06-23T06:13:01.634Z",
      '  intent: "Adjust redis-cache"',
      "  provider: unknown",
      "  generatedBy: unknown",
      "  envFileSources: {}",
      "services:",
      "  redis:",
      "    image: redis:7",
    ].join("\n");
    const app = render(
      React.createElement(PlanPreview, {
        composeYaml,
        diff,
        onAnswer: () => {},
      }),
      {
        stdout: stdout as unknown as NodeJS.WriteStream,
        stdin: stdin as unknown as NodeJS.ReadStream,
        debug: true,
        patchConsole: false,
        exitOnCtrlC: false,
      },
    );

    await new Promise((resolve) => setImmediate(resolve));
    stdin.push("x");
    stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));

    const output = lastRenderedFrame(stdout.output());
    expect(output).not.toContain("x-docker-agent");
    expect(output).not.toContain("createdAt");
    expect(output).not.toContain("lastApplied");
    expect(output).toContain("services:");
    expect(output).toContain("image: redis:7");

    app.unmount();
    app.cleanup();
  });

  test("renders expanded YAML with one terminal row per YAML line", async () => {
    const stdin = new TestStdin();
    const stdout = new TestStdout();
    const app = render(
      React.createElement(PlanPreview, {
        composeYaml: "services:\n  app:\n    image: nginx:latest",
        diff,
        onAnswer: () => {},
      }),
      {
        stdout: stdout as unknown as NodeJS.WriteStream,
        stdin: stdin as unknown as NodeJS.ReadStream,
        debug: true,
        patchConsole: false,
        exitOnCtrlC: false,
      },
    );

    await new Promise((resolve) => setImmediate(resolve));
    stdin.push("x");
    stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));

    const lines = lastRenderedFrame(stdout.output()).split("\n");
    const servicesLine = lines.findIndex((line) => line.includes("services:"));
    const appLine = lines.findIndex((line) => line.includes("app:"));
    const imageLine = lines.findIndex((line) => line.includes("image: nginx:latest"));

    expect(servicesLine).toBeGreaterThan(-1);
    expect(appLine).toBe(servicesLine + 1);
    expect(imageLine).toBe(appLine + 1);

    app.unmount();
    app.cleanup();
  });
});

describe("PlanPreview config files", () => {
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

  test("lists config files and reveals content on 'c'", async () => {
    const stdin = new TestStdin();
    const stdout = new TestStdout();
    const app = render(
      React.createElement(PlanPreview, {
        composeYaml: "services: {}",
        diff,
        configFiles: [{ path: "nginx.conf", content: "events {}", bytes: 9 }],
        onAnswer: () => {},
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

    expect(stripAnsi(stdout.output())).toContain("nginx.conf");
    // collapsed: content not shown
    expect(stripAnsi(stdout.output())).not.toContain("events {}");

    // Ink reads keypresses via the stdin 'readable' event (App.handleReadable).
    stdin.push("c");
    stdin.emit("readable");
    await new Promise((r) => setImmediate(r));
    expect(stripAnsi(stdout.output())).toContain("events {}");
  });

  test("masks secrets in expanded YAML and config content", async () => {
    const stdin = new TestStdin();
    const stdout = new TestStdout();
    const app = render(
      React.createElement(PlanPreview, {
        composeYaml: "services:\n  app:\n    password: yaml-secret",
        diff,
        configFiles: [{ path: "app.env", content: "apiKey=config-secret", bytes: 20 }],
        onAnswer: () => {},
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
    await new Promise((resolve) => setImmediate(resolve));
    stdin.push("c");
    stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));
    stdin.push("x");
    stdin.emit("readable");
    await new Promise((resolve) => setImmediate(resolve));
    const output = stripAnsi(stdout.output());
    expect(output).not.toContain("yaml-secret");
    expect(output).not.toContain("config-secret");
    expect(output).toContain("***");
  });
});
