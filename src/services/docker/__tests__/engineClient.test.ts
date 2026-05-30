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
    });
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
