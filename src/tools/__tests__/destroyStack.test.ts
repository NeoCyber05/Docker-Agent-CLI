import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ToolContext } from "src/Tool";
import { StateStore } from "src/state/StateStore";
import { destroyAllStacks } from "src/tools/destroyAllStacks";
import { destroyStack } from "src/tools/destroyStack";
import { beforeEach, describe, expect, test } from "vitest";
import { MockComposeRunner } from "../../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../../tests/mocks/mockDockerEngine";

async function drain<T, R>(g: AsyncGenerator<T, R>): Promise<R> {
  let r: IteratorResult<T, R>;
  while (true) {
    r = await g.next();
    if (r.done) return r.value;
  }
}

function seedStack(store: StateStore, name: string) {
  store.write(name, {
    "x-docker-agent": {
      name,
      createdAt: "x",
      lastApplied: "x",
      intent: "x",
      provider: "x",
      generatedBy: "x",
      envFileSources: {},
    },
    services: { web: { image: "nginx:1.27" } },
  });
}

describe("destroy_stack / destroy_all_stacks", () => {
  let tmpRoot: string;
  let store: StateStore;
  let runner: MockComposeRunner;
  let ctx: ToolContext;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "destroy-"));
    store = new StateStore(path.join(tmpRoot, ".docker-agent"));
    runner = new MockComposeRunner(tmpRoot);
    ctx = {
      cwd: tmpRoot,
      stateStore: store,
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: runner as never,
      abortSignal: new AbortController().signal,
    };
  });

  test("destroyStack calls forStack(name).down()", async () => {
    seedStack(store, "webapp");

    const result = await drain(
      destroyStack.call({ stackName: "webapp", removeVolumes: true }, ctx),
    );

    expect(result.ok).toBe(true);
    expect(runner.forStackCalls[0]).toMatchObject({ stackName: "webapp" });
    expect(runner.boundFor("webapp").downCalls[0]).toEqual({ volumes: true });
  });

  test("destroyAllStacks invokes down for each stack", async () => {
    seedStack(store, "a");
    seedStack(store, "b");

    const result = await drain(destroyAllStacks.call({}, ctx));

    expect(result.destroyed.sort()).toEqual(["a", "b"]);
    expect(runner.forStackCalls.map((c) => c.stackName).sort()).toEqual(["a", "b"]);
  });

  test("destroyAllStacks records per-stack failures and continues", async () => {
    seedStack(store, "a");
    seedStack(store, "b");
    ctx.composeRunner = {
      forStack: (stackName: string, yamlPath: string) => {
        if (stackName === "a") throw new Error("boom");
        return runner.forStack(stackName, yamlPath);
      },
    } as never;

    const result = await drain(destroyAllStacks.call({}, ctx));

    expect(result.destroyed).toEqual(["b"]);
    expect(result.failed).toEqual([{ stack: "a", exitCode: -1 }]);
    expect(runner.forStackCalls.map((c) => c.stackName)).toEqual(["b"]);
  });
});
