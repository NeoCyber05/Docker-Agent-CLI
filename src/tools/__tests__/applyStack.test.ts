import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ToolContext } from "src/Tool";
import type { ImageValidator } from "src/services/docker/imageValidator";
import { StateStore } from "src/state/StateStore";
import { applyStack, verifyHealth } from "src/tools/applyStack";
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

function invalidImageValidator(image: string): ImageValidator {
  return {
    validateImage: async () => ({
      image,
      status: "invalid",
      source: "registry",
      error: "manifest not found",
      suggestion: "postgres:17-alpine",
    }),
    validateImages: async () => [
      {
        image,
        status: "invalid",
        source: "registry",
        error: "manifest not found",
        suggestion: "postgres:17-alpine",
      },
    ],
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

    // Pre-create the bound runner and configure it to return healthy services for the health gate
    const yamlPath = path.join(tmpRoot, ".docker-agent/stacks/webapp.yaml");
    const preCreated = runner.forStack("webapp", yamlPath);
    preCreated.setRunningServices(["web"]);
    // Reset forStackCalls so the test assertion sees the call from applyStack (index 0)
    runner.forStackCalls.length = 0;

    const result = await drain(
      applyStack.call({ stackName: "webapp", composeYaml: yaml, scaleOverrides: { web: 2 } }, ctx),
    );

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
        ps: async () => [{ Name: "webapp-web-1", Service: "web", State: "running" }],
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

  test("rejects invalid image tags before writing state or running compose", async () => {
    const runner = new MockComposeRunner(tmpRoot);
    const ctx = makeCtx(tmpRoot, runner);
    ctx.imageValidator = invalidImageValidator("postgres:99-alpine");
    const yaml =
      "x-docker-agent:\n  name: bad\n  createdAt: '2026-05-26T00:00:00.000Z'\n  lastApplied: null\n  intent: test\n  provider: test\n  generatedBy: test\n  envFileSources: {}\nservices:\n  db:\n    image: postgres:99-alpine\n";

    const result = await drain(applyStack.call({ stackName: "bad", composeYaml: yaml }, ctx));

    expect(result).toMatchObject({
      ok: false,
      exitCode: 1,
      errorOutput: expect.stringContaining("Invalid Docker images detected"),
    });
    expect(runner.forStackCalls).toEqual([]);
    expect(ctx.stateStore.read("bad")).toBeNull();
  });
});

describe("verifyHealth", () => {
  const noAbort = new AbortController().signal;
  type Row = { Name: string; Service: string; State: string; Health?: string };
  function boundWith(rows: Row[]) {
    return { ps: async () => rows } as never;
  }

  test("healthy once every service is running", async () => {
    const r = await verifyHealth(
      boundWith([{ Name: "s-web-1", Service: "web", State: "running" }]),
      ["web"],
      10_000,
      noAbort,
    );
    expect(r).toEqual({ healthy: true, unhealthy: [] });
  });

  test("fails fast on a crashed (exited) container without waiting the deadline", async () => {
    const start = Date.now();
    const r = await verifyHealth(
      boundWith([
        { Name: "s-web-1", Service: "web", State: "running" },
        { Name: "s-db-1", Service: "db", State: "exited" },
      ]),
      ["web", "db"],
      60_000,
      noAbort,
    );
    expect(r.healthy).toBe(false);
    expect(r.unhealthy).toEqual([{ service: "db", status: "exited" }]);
    expect(Date.now() - start).toBeLessThan(1_000);
  });

  test("reports a not-created service with a status", async () => {
    const r = await verifyHealth(boundWith([]), ["web"], 0, noAbort);
    expect(r.healthy).toBe(false);
    expect(r.unhealthy).toEqual([{ service: "web", status: "not created" }]);
  });

  test("uses the health field when a healthcheck is present", async () => {
    const r = await verifyHealth(
      boundWith([{ Name: "s-db-1", Service: "db", State: "running", Health: "unhealthy" }]),
      ["db"],
      0,
      noAbort,
    );
    expect(r.healthy).toBe(false);
    expect(r.unhealthy).toEqual([{ service: "db", status: "health: unhealthy" }]);
  });
});
