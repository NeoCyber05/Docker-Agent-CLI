import type { ToolContext } from "src/Tool";
import type { EngineClient } from "src/services/docker/engineClient";
import { type HealthRow, getHealth } from "src/tools/getHealth";
import { describe, expect, test, vi } from "vitest";

const MB = 1024 * 1024;

async function drain<T, R>(g: AsyncGenerator<T, R>): Promise<R> {
  let r: IteratorResult<T, R>;
  while (true) {
    r = await g.next();
    if (r.done) return r.value;
  }
}

function ctxWith(engine: Partial<EngineClient>): ToolContext {
  return {
    cwd: "/cwd",
    stateStore: {} as never,
    dockerEngine: engine as EngineClient,
    composeRunner: {} as never,
    abortSignal: new AbortController().signal,
  };
}

const goodStats = {
  cpu_stats: {
    cpu_usage: { total_usage: 200, percpu_usage: [1, 2] },
    system_cpu_usage: 2000,
    online_cpus: 2,
  },
  precpu_stats: { cpu_usage: { total_usage: 100 }, system_cpu_usage: 1000 },
  memory_stats: { usage: 50 * MB, limit: 100 * MB },
};

describe("get_health", () => {
  test("requests all containers (includes exited/restarting) with the project label filter", async () => {
    const listContainers = vi.fn(async () => []);
    const engine = { listContainers, inspect: vi.fn(), stats: vi.fn() };
    await drain(getHealth.call({ stackName: "web" }, ctxWith(engine)));

    expect(listContainers).toHaveBeenCalledWith({
      all: true,
      filters: { label: ["com.docker.compose.project=web"] },
    });
  });

  test("maps a running container with cpu/mem and no crash loop", async () => {
    const engine: Partial<EngineClient> = {
      listContainers: async () => [
        {
          Id: "c1",
          Names: ["/web-1"],
          State: "running",
          Labels: { "com.docker.compose.service": "web" },
        },
      ],
      inspect: async () => ({
        Id: "c1",
        Name: "/web-1",
        State: { Status: "running", Health: { Status: "healthy" } },
        Config: { Image: "nginx", Env: [], Cmd: null, Labels: {} },
        HostConfig: { Binds: null, PortBindings: {} },
        NetworkSettings: { Ports: {} },
        RestartCount: 0,
      }),
      stats: async () => goodStats as never,
    };

    const result = await drain(getHealth.call({ stackName: "web" }, ctxWith(engine)));
    expect(result.containers).toHaveLength(1);
    const row = result.containers[0] as HealthRow;
    expect(row.service).toBe("web");
    expect(row.status).toBe("running");
    expect(row.health).toBe("healthy");
    expect(row.cpuPercent).toBeCloseTo(20);
    expect(row.memUsedMb).toBeCloseTo(50);
    expect(row.crashLoop).toBe(false);
    expect(result.crashLoops).toEqual([]);
  });

  test("crashLoop is false at 2 restarts and true at 3 (threshold boundary)", async () => {
    const makeEngine = (restartCount: number): Partial<EngineClient> => ({
      listContainers: async () => [
        {
          Id: "c1",
          Names: ["/db-1"],
          State: "running",
          Labels: { "com.docker.compose.service": "db" },
        },
      ],
      inspect: async () => ({
        Id: "c1",
        Name: "/db-1",
        State: { Status: "running" },
        Config: { Image: "postgres", Env: [], Cmd: null, Labels: {} },
        HostConfig: { Binds: null, PortBindings: {} },
        NetworkSettings: { Ports: {} },
        RestartCount: restartCount,
      }),
      stats: async () => goodStats as never,
    });

    const two = await drain(getHealth.call({ stackName: "s" }, ctxWith(makeEngine(2))));
    expect((two.containers[0] as HealthRow).crashLoop).toBe(false);

    const three = await drain(getHealth.call({ stackName: "s" }, ctxWith(makeEngine(3))));
    expect((three.containers[0] as HealthRow).crashLoop).toBe(true);
    expect(three.crashLoops).toEqual(["/db-1"]);
  });

  test("restarting status flags a crash loop regardless of count", async () => {
    const engine: Partial<EngineClient> = {
      listContainers: async () => [
        {
          Id: "c1",
          Names: ["/w-1"],
          State: "restarting",
          Labels: { "com.docker.compose.service": "w" },
        },
      ],
      inspect: async () => ({
        Id: "c1",
        Name: "/w-1",
        State: { Status: "restarting" },
        Config: { Image: "x", Env: [], Cmd: null, Labels: {} },
        HostConfig: { Binds: null, PortBindings: {} },
        NetworkSettings: { Ports: {} },
        RestartCount: 0,
      }),
      stats: async () => goodStats as never,
    };
    const result = await drain(getHealth.call({ stackName: "s" }, ctxWith(engine)));
    expect((result.containers[0] as HealthRow).crashLoop).toBe(true);
  });

  test("returns an exited container (relies on all:true) with null cpu/mem", async () => {
    const engine: Partial<EngineClient> = {
      listContainers: async () => [
        {
          Id: "c1",
          Names: ["/job-1"],
          State: "exited",
          Labels: { "com.docker.compose.service": "job" },
        },
      ],
      inspect: async () => ({
        Id: "c1",
        Name: "/job-1",
        State: { Status: "exited" },
        Config: { Image: "x", Env: [], Cmd: null, Labels: {} },
        HostConfig: { Binds: null, PortBindings: {} },
        NetworkSettings: { Ports: {} },
        RestartCount: 0,
      }),
      // exited containers commonly fail stats
      stats: async () => {
        throw new Error("no stats for stopped container");
      },
    };
    const result = await drain(getHealth.call({ stackName: "s" }, ctxWith(engine)));
    const row = result.containers[0] as HealthRow;
    expect(row.status).toBe("exited");
    expect(row.cpuPercent).toBeNull();
    expect(row.error).toBeTruthy();
  });

  test("inspect failure for one container is isolated; others fine", async () => {
    const engine: Partial<EngineClient> = {
      listContainers: async () => [
        {
          Id: "bad",
          Names: ["/bad-1"],
          State: "running",
          Labels: { "com.docker.compose.service": "bad" },
        },
        {
          Id: "ok",
          Names: ["/ok-1"],
          State: "running",
          Labels: { "com.docker.compose.service": "ok" },
        },
      ],
      inspect: async (id: string) => {
        if (id === "bad") throw new Error("container vanished");
        return {
          Id: "ok",
          Name: "/ok-1",
          State: { Status: "running", Health: { Status: "healthy" } },
          Config: { Image: "x", Env: [], Cmd: null, Labels: {} },
          HostConfig: { Binds: null, PortBindings: {} },
          NetworkSettings: { Ports: {} },
          RestartCount: 0,
        };
      },
      stats: async () => goodStats as never,
    };
    const result = await drain(getHealth.call({ stackName: "s" }, ctxWith(engine)));
    const bad = result.containers.find((r) => r.name === "/bad-1") as HealthRow;
    const ok = result.containers.find((r) => r.name === "/ok-1") as HealthRow;
    expect(bad.error).toBeTruthy();
    expect(bad.status).toBe("running"); // from list summary
    expect(bad.restartCount).toBe(0);
    expect(ok.error).toBeUndefined();
    expect(ok.health).toBe("healthy");
  });

  test("stats failure preserves inspect-derived restartCount/health", async () => {
    const engine: Partial<EngineClient> = {
      listContainers: async () => [
        {
          Id: "c1",
          Names: ["/web-1"],
          State: "running",
          Labels: { "com.docker.compose.service": "web" },
        },
      ],
      inspect: async () => ({
        Id: "c1",
        Name: "/web-1",
        State: { Status: "running", Health: { Status: "healthy" } },
        Config: { Image: "x", Env: [], Cmd: null, Labels: {} },
        HostConfig: { Binds: null, PortBindings: {} },
        NetworkSettings: { Ports: {} },
        RestartCount: 5,
      }),
      stats: async () => {
        throw new Error("stats unavailable");
      },
    };
    const result = await drain(getHealth.call({ stackName: "s" }, ctxWith(engine)));
    const row = result.containers[0] as HealthRow;
    expect(row.cpuPercent).toBeNull();
    expect(row.memUsedMb).toBeNull();
    expect(row.health).toBe("healthy"); // preserved from inspect
    expect(row.restartCount).toBe(5); // preserved from inspect
    expect(row.crashLoop).toBe(true); // 5 >= 3
    expect(row.error).toBeTruthy();
  });

  test("first-sample stats (no precpu_stats) yields cpuPercent null", async () => {
    const engine: Partial<EngineClient> = {
      listContainers: async () => [
        {
          Id: "c1",
          Names: ["/web-1"],
          State: "running",
          Labels: { "com.docker.compose.service": "web" },
        },
      ],
      inspect: async () => ({
        Id: "c1",
        Name: "/web-1",
        State: { Status: "running" },
        Config: { Image: "x", Env: [], Cmd: null, Labels: {} },
        HostConfig: { Binds: null, PortBindings: {} },
        NetworkSettings: { Ports: {} },
        RestartCount: 0,
      }),
      stats: async () =>
        ({
          cpu_stats: { cpu_usage: { total_usage: 200 }, system_cpu_usage: 2000, online_cpus: 1 },
          memory_stats: { usage: MB, limit: 2 * MB },
        }) as never,
    };
    const result = await drain(getHealth.call({ stackName: "s" }, ctxWith(engine)));
    expect((result.containers[0] as HealthRow).cpuPercent).toBeNull();
    expect((result.containers[0] as HealthRow).memUsedMb).toBeCloseTo(1);
  });

  test("top-level engine failure returns an error result, not a throw", async () => {
    const engine: Partial<EngineClient> = {
      listContainers: async () => {
        throw new Error("docker daemon down");
      },
    };
    const result = await drain(getHealth.call({ stackName: "s" }, ctxWith(engine)));
    expect(result.containers).toEqual([]);
    expect(result.error).toContain("docker daemon down");
  });
});
