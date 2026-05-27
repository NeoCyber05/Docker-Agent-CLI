import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ToolContext } from "src/Tool";
import { StateStore } from "src/state/StateStore";
import { applyStack } from "src/tools/applyStack";
import { beforeEach, describe, expect, test } from "vitest";
import { MockComposeRunner } from "../../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../../tests/mocks/mockDockerEngine";

async function drain<T, R>(gen: AsyncGenerator<T, R>): Promise<R> {
  let r: IteratorResult<T, R>;
  while (true) {
    r = await gen.next();
    if (r.done) return r.value;
  }
}

async function drainWithProgress<R>(
  gen: AsyncGenerator<{ type: "progress"; msg: string }, R>,
): Promise<{ progress: string[]; result: R }> {
  const progress: string[] = [];
  while (true) {
    const r = await gen.next();
    if (r.done) return { progress, result: r.value };
    progress.push(r.value.msg);
  }
}

function makeCtx(tmpRoot: string, composeRunner: MockComposeRunner): ToolContext {
  return {
    cwd: tmpRoot,
    stateStore: new StateStore(path.join(tmpRoot, ".docker-agent")),
    dockerEngine: new MockDockerEngine() as never,
    composeRunner: composeRunner as never,
    abortSignal: new AbortController().signal,
  };
}

describe("apply_stack", () => {
  let tmpRoot: string;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "apply-"));
  });

  test("writes stack YAML then calls composeRunner.forStack().up()", async () => {
    const runner = new MockComposeRunner(tmpRoot);
    const ctx = makeCtx(tmpRoot, runner);
    const yaml =
      "x-docker-agent:\n  name: webapp\n  createdAt: '2026-05-26T00:00:00.000Z'\n  lastApplied: null\n  intent: test\n  provider: test\n  generatedBy: test\n  envFileSources: {}\nservices:\n  web:\n    image: nginx:1.27\n";
    const result = await drain(
      applyStack.call({ stackName: "webapp", composeYaml: yaml, scaleOverrides: { web: 2 } }, ctx),
    );

    const yamlPath = path.join(tmpRoot, ".docker-agent/stacks/webapp.yaml");
    expect(result).toMatchObject({ ok: true });
    expect(fs.existsSync(yamlPath)).toBe(true);
    expect(runner.forStackCalls[0]).toMatchObject({
      stackName: "webapp",
      yamlPath,
    });
    expect(runner.boundFor("webapp").cwd).toBe(tmpRoot);
    expect(runner.boundFor("webapp").upCalls[0]).toEqual({
      detach: true,
      scale: { web: 2 },
    });
    expect(ctx.stateStore.read("webapp")?.["x-docker-agent"].lastApplied).toEqual(
      expect.any(String),
    );
  });

  test("refuses tracked env_file paths before running compose", async () => {
    spawnSync("git", ["init"], { cwd: tmpRoot, stdio: "ignore" });
    fs.writeFileSync(path.join(tmpRoot, ".env.api"), "API_KEY=tracked\n");
    spawnSync("git", ["add", ".env.api"], { cwd: tmpRoot, stdio: "ignore" });

    const runner = new MockComposeRunner(tmpRoot);
    const ctx = makeCtx(tmpRoot, runner);
    const yaml =
      "x-docker-agent:\n  name: webapp\n  createdAt: '2026-05-26T00:00:00.000Z'\n  lastApplied: null\n  intent: test\n  provider: test\n  generatedBy: test\n  envFileSources: {}\nservices:\n  web:\n    image: nginx:1.27\n    env_file:\n      - .env.api\n";

    const result = await drain(applyStack.call({ stackName: "webapp", composeYaml: yaml }, ctx));

    expect(result.ok).toBe(false);
    expect(result.errorOutput).toContain(".env.api is tracked by git");
    expect(runner.forStackCalls).toEqual([]);
  });

  test("scrubs secret key output from compose progress", async () => {
    fs.mkdirSync(path.join(tmpRoot, ".docker-agent", "secrets"), { recursive: true });
    fs.writeFileSync(
      path.join(tmpRoot, ".docker-agent", "secrets", "webapp-web.env"),
      "API_KEY=leakvalue\n",
    );
    const ctx = makeCtx(tmpRoot, new MockComposeRunner(tmpRoot));
    ctx.composeRunner = {
      forStack: () => ({
        up: async function* () {
          yield "API_KEY=leakvalue\n";
          return 0;
        },
      }),
    } as never;
    const yaml =
      "x-docker-agent:\n  name: webapp\n  createdAt: '2026-05-26T00:00:00.000Z'\n  lastApplied: null\n  intent: test\n  provider: test\n  generatedBy: test\n  envFileSources: {}\nservices:\n  web:\n    image: nginx:1.27\n    env_file:\n      - ./.docker-agent/secrets/webapp-web.env\n";

    const { progress } = await drainWithProgress(
      applyStack.call({ stackName: "webapp", composeYaml: yaml }, ctx),
    );

    expect(progress.join("\n")).toContain("API_KEY=***");
    expect(progress.join("\n")).not.toContain("leakvalue");
  });
});
