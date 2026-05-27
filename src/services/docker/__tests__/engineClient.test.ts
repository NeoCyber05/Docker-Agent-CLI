import { createEngineClient } from "src/services/docker/engineClient";
import { beforeEach, describe, expect, test, vi } from "vitest";

const dockerMock = vi.hoisted(() => {
  const docker = {
    listContainers: vi.fn(),
    getContainer: vi.fn(),
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
});
