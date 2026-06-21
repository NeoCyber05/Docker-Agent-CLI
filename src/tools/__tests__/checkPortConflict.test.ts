import type { ToolContext } from "src/Tool";
import type { ComposeRunner } from "src/services/docker/composeRunner";
import { StateStore } from "src/state/StateStore";
import { checkPortConflicts, parsePublishedPorts } from "src/tools/checkPortConflict";
import { describe, expect, test } from "vitest";
import { MockComposeRunner } from "../../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../../tests/mocks/mockDockerEngine";

function makeCtx(engine: MockDockerEngine): ToolContext {
  return {
    cwd: "/tmp",
    stateStore: new StateStore("/tmp/.docker-agent"),
    dockerEngine: engine as never,
    composeRunner: new MockComposeRunner() as unknown as ComposeRunner,
    abortSignal: new AbortController().signal,
  };
}

function engineWithPublishedPort({
  id,
  project,
  hostPort,
  containerPort,
}: {
  id: string;
  project: string;
  hostPort: string;
  containerPort: string;
}): MockDockerEngine {
  const engine = new MockDockerEngine();
  engine.containers.push({
    Id: id,
    Names: [`/${id}`],
    State: "running",
    Labels: { "com.docker.compose.project": project },
  });
  engine.inspectById.set(id, {
    NetworkSettings: {
      Ports: { [containerPort]: [{ HostIp: "0.0.0.0", HostPort: hostPort }] },
    },
  });
  return engine;
}

describe("check_port_conflict", () => {
  test.each([
    ["80", []],
    ["8080:80", [{ hostIp: "0.0.0.0", hostPort: 8080, containerPort: 80, protocol: "tcp" }]],
    [
      "127.0.0.1:5353:53/udp",
      [{ hostIp: "127.0.0.1", hostPort: 5353, containerPort: 53, protocol: "udp" }],
    ],
  ])("parses %s", (value, expected) => {
    expect(parsePublishedPorts(value)).toEqual(expected);
  });

  test("reports draft and running-container conflicts", async () => {
    const engine = new MockDockerEngine();
    engine.containers.push({
      Id: "existing",
      Names: ["/existing"],
      State: "running",
      Labels: {},
    });
    engine.inspectById.set("existing", {
      NetworkSettings: {
        Ports: { "80/tcp": [{ HostIp: "0.0.0.0", HostPort: "8080" }] },
      },
    });

    const result = await checkPortConflicts(
      "app",
      {
        api: { image: "example/api:1", ports: ["8080:80"] },
        admin: { image: "example/admin:1", ports: ["8080:8080"] },
      },
      makeCtx(engine),
    );

    expect(result.ok).toBe(false);
    expect(new Set(result.conflicts.map((item) => item.source))).toEqual(
      new Set(["draft", "running"]),
    );
  });

  test("ignores bindings owned by the stack being updated", async () => {
    const engine = engineWithPublishedPort({
      id: "own-web",
      project: "app",
      hostPort: "8080",
      containerPort: "80/tcp",
    });
    const result = await checkPortConflicts(
      "app",
      { web: { image: "nginx:1.27-alpine", ports: ["8080:80"] } },
      makeCtx(engine),
    );
    expect(result).toMatchObject({ ok: true, conflicts: [] });
  });

  test("tcp and udp on same host port do not conflict", async () => {
    const result = await checkPortConflicts(
      "dns",
      {
        dnsTcp: { image: "example/dns:1", ports: ["5353:53/tcp"] },
        dnsUdp: { image: "example/dns:1", ports: ["5353:53/udp"] },
      },
      makeCtx(new MockDockerEngine()),
    );
    expect(result.ok).toBe(true);
  });
});
