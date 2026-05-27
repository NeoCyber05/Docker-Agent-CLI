import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { StateStore } from "src/state/StateStore";
import { listStacks } from "src/tools/listStacks";
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

describe("list_stacks", () => {
  let tmpRoot: string;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "list-"));
  });

  test("returns summary list", async () => {
    const store = new StateStore(path.join(tmpRoot, ".docker-agent"));
    store.write("a", {
      "x-docker-agent": {
        name: "a",
        createdAt: "x",
        lastApplied: null,
        intent: "x",
        provider: "x",
        generatedBy: "x",
        envFileSources: {},
      },
      services: { web: { image: "nginx" } },
    });

    const result = await drain(
      listStacks.call(
        {},
        {
          cwd: tmpRoot,
          stateStore: store,
          dockerEngine: new MockDockerEngine() as never,
          composeRunner: new MockComposeRunner(tmpRoot) as never,
          abortSignal: new AbortController().signal,
        },
      ),
    );

    expect(result.stacks.map((s) => s.name)).toEqual(["a"]);
  });
});
