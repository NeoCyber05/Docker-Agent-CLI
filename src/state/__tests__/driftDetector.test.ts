import { describe, expect, test } from "vitest";
import { detectDrift } from "src/state/driftDetector";
import { StateStore } from "src/state/StateStore";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

function makeEngine(containers: Array<{
  Id: string;
  Service: string;
  Image: string;
  Env: string[];
  State: string;
}>) {
  return {
    listContainers: async () =>
      containers.map((c) => ({
        Id: c.Id,
        Names: [`/${c.Service}-1`],
        State: c.State,
        Labels: {
          "com.docker.compose.project": "test",
          "com.docker.compose.service": c.Service,
        },
      })),
    inspect: async (id: string) => {
      const c = containers.find((x) => x.Id === id)!;
      return {
        Id: c.Id,
        Name: `/${c.Service}-1`,
        State: { Status: c.State },
        Config: {
          Image: c.Image,
          Env: c.Env,
          Cmd: null,
          Labels: {
            "com.docker.compose.project": "test",
            "com.docker.compose.service": c.Service,
          },
        },
        HostConfig: { Binds: null, PortBindings: {} },
        NetworkSettings: { Ports: {} },
      };
    },
  };
}

describe("detectDrift", () => {
  let tmpRoot: string;
  let store: StateStore;

  test("in_sync when actual matches desired", async () => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "drift-"));
    store = new StateStore(tmpRoot);
    store.write("test", {
      "x-docker-agent": {
        name: "test",
        createdAt: "x",
        lastApplied: "x",
        intent: "x",
        provider: "x",
        generatedBy: "x",
        envFileSources: {},
      },
      services: { web: { image: "nginx:1.27", environment: { NODE_ENV: "prod" } } },
    });
    const engine = makeEngine([
      { Id: "c1", Service: "web", Image: "nginx:1.27", Env: ["NODE_ENV=prod"], State: "running" },
    ]);
    const report = await detectDrift("test", store, engine);
    expect(report.status).toBe("in_sync");
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  test("drift when image differs", async () => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "drift-"));
    store = new StateStore(tmpRoot);
    store.write("test", {
      "x-docker-agent": {
        name: "test",
        createdAt: "x",
        lastApplied: "x",
        intent: "x",
        provider: "x",
        generatedBy: "x",
        envFileSources: {},
      },
      services: { web: { image: "nginx:1.27" } },
    });
    const engine = makeEngine([
      { Id: "c1", Service: "web", Image: "nginx:1.25", Env: [], State: "running" },
    ]);
    const report = await detectDrift("test", store, engine);
    expect(report.status).toBe("drift");
    expect(report.serviceDiffs[0]?.changes).toContainEqual(
      expect.objectContaining({ field: "image", from: "nginx:1.27", to: "nginx:1.25" }),
    );
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  test("missing when stack defined but no containers", async () => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "drift-"));
    store = new StateStore(tmpRoot);
    store.write("test", {
      "x-docker-agent": {
        name: "test",
        createdAt: "x",
        lastApplied: "x",
        intent: "x",
        provider: "x",
        generatedBy: "x",
        envFileSources: {},
      },
      services: { web: { image: "nginx:1.27" } },
    });
    const engine = makeEngine([]);
    const report = await detectDrift("test", store, engine);
    expect(report.status).toBe("missing");
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  test("secret value change reported as 'value changed' without leaking", async () => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "drift-"));
    store = new StateStore(tmpRoot);
    store.write("test", {
      "x-docker-agent": {
        name: "test",
        createdAt: "x",
        lastApplied: "x",
        intent: "x",
        provider: "x",
        generatedBy: "x",
        envFileSources: {},
      },
      services: { web: { image: "nginx:1.27", environment: { API_KEY: "old" } } },
    });
    const engine = makeEngine([
      { Id: "c1", Service: "web", Image: "nginx:1.27", Env: ["API_KEY=new"], State: "running" },
    ]);
    const report = await detectDrift("test", store, engine);
    const change = report.serviceDiffs[0]?.changes.find((c) => c.field === "env.API_KEY");
    expect(change).toMatchObject({ from: "***", to: "***" });
    expect(JSON.stringify(report)).not.toContain("old");
    expect(JSON.stringify(report)).not.toContain("new");
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  test("replica count mismatch reported", async () => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "drift-"));
    store = new StateStore(tmpRoot);
    store.write("test", {
      "x-docker-agent": {
        name: "test",
        createdAt: "x",
        lastApplied: "x",
        intent: "x",
        provider: "x",
        generatedBy: "x",
        envFileSources: {},
      },
      services: { api: { image: "node:20", scale: 3 } },
    });
    const engine = makeEngine([
      { Id: "c1", Service: "api", Image: "node:20", Env: [], State: "running" },
      { Id: "c2", Service: "api", Image: "node:20", Env: [], State: "running" },
    ]);
    const report = await detectDrift("test", store, engine);
    const change = report.serviceDiffs[0]?.changes.find((c) => c.field === "replicaCount");
    expect(change).toMatchObject({ from: 3, to: 2 });
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });
});