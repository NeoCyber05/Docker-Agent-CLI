import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ToolContext } from "src/Tool";
import { StateStore } from "src/state/StateStore";
import { getStackStatus } from "src/tools/getStackStatus";
import { beforeEach, describe, expect, test } from "vitest";
import { MockComposeRunner } from "../../../tests/mocks/mockComposeRunner";

async function drain<T, R>(g: AsyncGenerator<T, R>): Promise<R> {
  let r: IteratorResult<T, R>;
  while (true) {
    r = await g.next();
    if (r.done) return r.value;
  }
}

describe("get_stack_status logTail redaction", () => {
  let tmpRoot: string;
  let store: StateStore;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "status-"));
    store = new StateStore(path.join(tmpRoot, ".docker-agent"));
  });

  test("scrubs secret values appearing in logTail", async () => {
    const dir = path.join(tmpRoot, ".docker-agent", "states");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, "web.yaml"), "services: {}\n");
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
        yield "boot PASSWORD=hunter2 ready\n";
        return 0;
      } as never;
    };

    const ctx: ToolContext = {
      cwd: tmpRoot,
      stateStore: store,
      dockerEngine: {} as never,
      composeRunner: runner as never,
      abortSignal: new AbortController().signal,
    };

    const result = await drain(getStackStatus.call({ stackName: "web" }, ctx));
    expect(result.logTail).toContain("PASSWORD=***");
    expect(result.logTail).not.toContain("hunter2");
  });
});
