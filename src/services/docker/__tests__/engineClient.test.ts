import { Readable } from "node:stream";
import { createEngineClient } from "src/services/docker/engineClient";
import { beforeEach, describe, expect, test, vi } from "vitest";

const dockerMock = vi.hoisted(() => {
  const docker = {
    listContainers: vi.fn(),
    getContainer: vi.fn(),
    getImage: vi.fn(),
    listImages: vi.fn(),
    pull: vi.fn(),
  };
  const Docker = vi.fn(() => docker);
  return { Docker, docker };
});

vi.mock("dockerode", () => ({ default: dockerMock.Docker }));

describe("EngineClient", () => {
  beforeEach(() => {
    dockerMock.Docker.mockClear();
    dockerMock.docker.listContainers.mockReset();
    dockerMock.docker.getContainer.mockReset();
    dockerMock.docker.getImage.mockReset();
    dockerMock.docker.listImages.mockReset();
    dockerMock.docker.pull.mockReset();
  });

  test("serializes label filters for dockerode and maps container summaries", async () => {
    dockerMock.docker.listContainers.mockResolvedValue([
      {
        Id: "abc123",
        Names: ["/api"],
        State: "running",
        Labels: { "com.docker.compose.project": "demo" },
        Image: "ignored-extra-field",
      },
    ]);

    const client = createEngineClient();
    const result = await client.listContainers({
      all: true,
      filters: { label: ["com.docker.compose.project=demo"] },
    });

    expect(dockerMock.docker.listContainers).toHaveBeenCalledWith({
      all: true,
      filters: JSON.stringify({ label: ["com.docker.compose.project=demo"] }),
    });
    expect(result).toEqual([
      {
        Id: "abc123",
        Names: ["/api"],
        State: "running",
        Labels: { "com.docker.compose.project": "demo" },
      },
    ]);
  });

  test("defaults listContainers to non-all without filters", async () => {
    dockerMock.docker.listContainers.mockResolvedValue([]);

    const client = createEngineClient();
    await client.listContainers({});

    expect(dockerMock.docker.listContainers).toHaveBeenCalledWith({ all: false });
  });

  test("validates container summary shape", async () => {
    dockerMock.docker.listContainers.mockResolvedValue([
      {
        Id: 123,
        Names: ["/api"],
        State: "running",
        Labels: {},
      },
    ]);

    const client = createEngineClient();

    await expect(client.listContainers({})).rejects.toThrow();
  });

  test("maps inspected containers to the public inspect shape", async () => {
    const inspect = vi.fn().mockResolvedValue({
      Id: "abc123",
      Name: "/api",
      State: { Status: "running", Health: { Status: "healthy" }, Extra: "ignored" },
      Config: {
        Image: "nginx:alpine",
        Env: ["NODE_ENV=production"],
        Cmd: null,
        Labels: { app: "api" },
        Extra: "ignored",
      },
      HostConfig: {
        Binds: null,
        PortBindings: { "80/tcp": [{ HostIp: "0.0.0.0", HostPort: "8080" }] },
        Extra: "ignored",
      },
      NetworkSettings: {
        Ports: { "80/tcp": [{ HostIp: "0.0.0.0", HostPort: "8080" }] },
        Extra: "ignored",
      },
      Extra: "ignored",
    });
    dockerMock.docker.getContainer.mockReturnValue({ inspect });

    const client = createEngineClient();
    const result = await client.inspect("abc123");

    expect(dockerMock.docker.getContainer).toHaveBeenCalledWith("abc123");
    expect(inspect).toHaveBeenCalledOnce();
    expect(result).toEqual({
      Id: "abc123",
      Name: "/api",
      State: { Status: "running", Health: { Status: "healthy" } },
      Config: {
        Image: "nginx:alpine",
        Env: ["NODE_ENV=production"],
        Cmd: null,
        Labels: { app: "api" },
      },
      HostConfig: {
        Binds: null,
        PortBindings: { "80/tcp": [{ HostIp: "0.0.0.0", HostPort: "8080" }] },
      },
      NetworkSettings: {
        Ports: { "80/tcp": [{ HostIp: "0.0.0.0", HostPort: "8080" }] },
      },
      RestartCount: 0,
    });
  });

  test("inspect includes RestartCount", async () => {
    const inspect = vi.fn().mockResolvedValue({
      Id: "abc123",
      Name: "/api",
      State: { Status: "running", Health: { Status: "healthy" } },
      Config: { Image: "nginx:alpine", Env: [], Cmd: null, Labels: {} },
      HostConfig: { Binds: null, PortBindings: {} },
      NetworkSettings: { Ports: {} },
      RestartCount: 4,
    });
    dockerMock.docker.getContainer.mockReturnValue({ inspect });

    const client = createEngineClient();
    const result = await client.inspect("abc123");

    expect(result.RestartCount).toBe(4);
  });

  test("stats parses cpu/mem fields and passes through extras", async () => {
    const stats = vi.fn().mockResolvedValue({
      cpu_stats: {
        cpu_usage: { total_usage: 200, percpu_usage: [1, 2] },
        system_cpu_usage: 2000,
        online_cpus: 2,
      },
      precpu_stats: { cpu_usage: { total_usage: 100 }, system_cpu_usage: 1000 },
      memory_stats: { usage: 50, limit: 100 },
      extra_field: "ignored",
    });
    dockerMock.docker.getContainer.mockReturnValue({ stats });

    const client = createEngineClient();
    const result = await client.stats("abc123");

    expect(dockerMock.docker.getContainer).toHaveBeenCalledWith("abc123");
    expect(stats).toHaveBeenCalledWith({ stream: false });
    expect(result.cpu_stats.cpu_usage.total_usage).toBe(200);
    expect(result.cpu_stats.online_cpus).toBe(2);
    expect(result.precpu_stats?.cpu_usage.total_usage).toBe(100);
    expect(result.memory_stats.usage).toBe(50);
    // .passthrough() preserves unknown fields.
    expect((result as Record<string, unknown>).extra_field).toBe("ignored");
  });

  test("stats allows missing precpu_stats (first sample)", async () => {
    const stats = vi.fn().mockResolvedValue({
      cpu_stats: { cpu_usage: { total_usage: 200 } },
      memory_stats: {},
    });
    dockerMock.docker.getContainer.mockReturnValue({ stats });

    const client = createEngineClient();
    const result = await client.stats("abc123");

    expect(result.precpu_stats).toBeUndefined();
    expect(result.memory_stats.usage).toBeUndefined();
  });

  test("returns null for missing images", async () => {
    const error = Object.assign(new Error("no such image"), { statusCode: 404 });
    dockerMock.docker.getImage.mockReturnValue({ inspect: vi.fn().mockRejectedValue(error) });

    const client = createEngineClient();

    await expect(client.inspectImage?.("postgres:99-alpine")).resolves.toBeNull();
  });

  test("validates inspected image shape", async () => {
    const inspect = vi.fn().mockResolvedValue({
      Id: "sha256:abc",
      RepoTags: ["nginx:1.27-alpine"],
      Size: 123,
      Architecture: "amd64",
      Os: "linux",
      Created: "2026-01-01T00:00:00Z",
      Extra: "ignored",
    });
    dockerMock.docker.getImage.mockReturnValue({ inspect });

    const client = createEngineClient();
    const result = await client.inspectImage?.("nginx:1.27-alpine");

    expect(result).toEqual({
      Id: "sha256:abc",
      RepoTags: ["nginx:1.27-alpine"],
      Size: 123,
      Architecture: "amd64",
      Os: "linux",
      Created: "2026-01-01T00:00:00Z",
    });
  });

  test("normalizes image summaries from listImages", async () => {
    dockerMock.docker.listImages.mockResolvedValue([
      {
        Id: "sha256:abc",
        RepoTags: null,
        Size: 123,
        Created: 1_789_000_000,
      },
    ]);

    const client = createEngineClient();
    const result = await client.listImages?.();

    expect(result).toEqual([
      {
        Id: "sha256:abc",
        RepoTags: [],
        Size: 123,
        Created: 1_789_000_000,
      },
    ]);
  });

  test("streams pull progress as readable messages", async () => {
    dockerMock.docker.pull.mockResolvedValue(
      Readable.from([
        '{"id":"layer-1","status":"Pull complete"}\n',
        '{"status":"Downloaded newer image"}\n',
      ]),
    );

    const client = createEngineClient();
    const progress: string[] = [];
    for await (const line of client.pullImage?.("nginx:1.27-alpine") ?? []) {
      progress.push(line);
    }

    expect(progress).toEqual(["layer-1 Pull complete", "Downloaded newer image"]);
  });
});
