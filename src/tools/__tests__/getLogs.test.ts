import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ToolContext } from "src/Tool";
import { StateStore } from "src/state/StateStore";
import { getLogs } from "src/tools/getLogs";
import { beforeEach, describe, expect, test } from "vitest";
import { MockComposeRunner } from "../../../tests/mocks/mockComposeRunner";

async function drain<T, R>(g: AsyncGenerator<T, R>): Promise<R> {
  let r: IteratorResult<T, R>;
  while (true) {
    r = await g.next();
    if (r.done) return r.value;
  }
}

describe("get_logs", () => {
  let tmpRoot: string;
  let store: StateStore;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "getlogs-"));
    store = new StateStore(path.join(tmpRoot, ".docker-agent"));
  });

  function writeStackYaml(name: string): void {
    const dir = path.join(tmpRoot, ".docker-agent", "stacks");
    fs.mkdirSync(dir, { recursive: true });
    // Minimal yaml file is enough — the tool only checks existence and uses composeRunner.
    fs.writeFileSync(path.join(dir, `${name}.yaml`), "services: {}\n");
  }

  function ctxWith(runner: MockComposeRunner): ToolContext {
    return {
      cwd: tmpRoot,
      stateStore: store,
      dockerEngine: {} as never,
      composeRunner: runner as never,
      abortSignal: new AbortController().signal,
    };
  }

  test("returns explanatory result when stack yaml is missing", async () => {
    const runner = new MockComposeRunner(tmpRoot);
    const result = await drain(getLogs.call({ stackName: "ghost" }, ctxWith(runner)));
    expect(result.logTail).toContain("ghost");
    expect(result.logTail.toLowerCase()).toContain("not found");
    expect(result.lineCount).toBe(0);
  });

  test("drains canned log lines and counts them", async () => {
    writeStackYaml("web");
    const runner = new MockComposeRunner(tmpRoot);
    runner.onBoundRunnerCreated = (b) => {
      b.logs = async function* () {
        yield "line one\n";
        yield "line two\n";
        return 0;
      } as never;
    };
    const result = await drain(getLogs.call({ stackName: "web" }, ctxWith(runner)));
    expect(result.logTail).toContain("line one");
    expect(result.logTail).toContain("line two");
    expect(result.lineCount).toBe(2);
    expect(result.truncated).toBe(false);
  });

  test("passes service and tailLines through to composeRunner.logs (no follow)", async () => {
    writeStackYaml("web");
    const runner = new MockComposeRunner(tmpRoot);
    await drain(getLogs.call({ stackName: "web", service: "api", tailLines: 25 }, ctxWith(runner)));
    const bound = runner.boundFor("web");
    expect(bound.logsCalls[0]).toMatchObject({ service: "api", tailLines: 25 });
    expect(bound.logsCalls[0]?.follow).toBeFalsy();
  });

  test("redacts secret values using collectSecretKeys", async () => {
    writeStackYaml("web");
    // Register a secret key via the stack environment.
    store.write("web", {
      "x-docker-agent": {
        name: "web",
        createdAt: "x",
        lastApplied: null,
        intent: "x",
        provider: "x",
        generatedBy: "x",
        envFileSources: {},
      },
      services: { web: { image: "nginx", environment: { PASSWORD: "hunter2" } } },
    });
    const runner = new MockComposeRunner(tmpRoot);
    runner.onBoundRunnerCreated = (b) => {
      b.logs = async function* () {
        yield "starting with PASSWORD=hunter2 in env\n";
        return 0;
      } as never;
    };
    const result = await drain(getLogs.call({ stackName: "web" }, ctxWith(runner)));
    expect(result.logTail).toContain("PASSWORD=***");
    expect(result.logTail).not.toContain("hunter2");
  });

  test("caps output to ~16KB keeping newest lines and sets truncated", async () => {
    writeStackYaml("web");
    const runner = new MockComposeRunner(tmpRoot);
    runner.onBoundRunnerCreated = (b) => {
      b.logs = async function* () {
        // 4000 lines of ~20 chars each = ~80KB, well over the 16KB cap.
        for (let i = 0; i < 4000; i++) yield `log line number ${i}\n`;
        return 0;
      } as never;
    };
    const result = await drain(getLogs.call({ stackName: "web" }, ctxWith(runner)));
    expect(result.truncated).toBe(true);
    expect(Buffer.byteLength(result.logTail, "utf-8")).toBeLessThanOrEqual(16 * 1024);
    // Newest line is kept; an early line is dropped.
    expect(result.logTail).toContain("log line number 3999");
    expect(result.logTail).not.toContain("log line number 0\n");
    // Chronological order is preserved even when truncated (regression for capNewest reverse).
    const keptLines = result.logTail.split("\n").filter(Boolean);
    const firstKept = Number(keptLines[0]!.replace("log line number ", ""));
    const lastKept = Number(keptLines[keptLines.length - 1]!.replace("log line number ", ""));
    expect(firstKept).toBeLessThan(lastKept);
    expect(lastKept).toBe(3999);
  });
});
