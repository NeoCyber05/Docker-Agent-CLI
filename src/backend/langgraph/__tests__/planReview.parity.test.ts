import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { QueryEngine } from "src/QueryEngine";
import type { ProviderEvent } from "src/services/api/types";
import { StateStore } from "src/state/StateStore";
import { afterEach, beforeEach, describe, expect, test } from "vitest";
import { MockComposeRunner } from "../../../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../../../tests/mocks/mockDockerEngine";

function fakeProvider(eventLists: ProviderEvent[][]) {
  let callIndex = 0;
  return {
    name: "fake",
    stream: async function* () {
      const events = eventLists[callIndex] ?? [];
      callIndex += 1;
      for (const ev of events) yield ev;
    },
  };
}

function planStackEvents(input: object): ProviderEvent[] {
  return [
    { type: "tool_use_start", id: "t1", name: "plan_stack" },
    { type: "tool_use_delta", id: "t1", argsPartialJson: JSON.stringify(input) },
    { type: "tool_use_stop", id: "t1" },
    { type: "message_stop", stopReason: "tool_use" },
  ];
}

function makeEngine({
  tmp,
  stateStore,
  composeRunner,
  providerEvents,
}: {
  tmp: string;
  stateStore: StateStore;
  composeRunner: MockComposeRunner;
  providerEvents: ProviderEvent[][];
}) {
  process.env.DOCKER_AGENT_BACKEND = "langgraph";
  return new QueryEngine({
    cwd: tmp,
    stateStore,
    dockerEngine: new MockDockerEngine() as never,
    composeRunner: composeRunner as never,
    provider: fakeProvider(providerEvents),
    healthCheckDeadlineMs: 0,
  });
}

describe("LangGraph plan_review parity", () => {
  let tmp: string;
  let stateStore: StateStore;
  let composeRunner: MockComposeRunner;
  const prevBackend = process.env.DOCKER_AGENT_BACKEND;

  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "lg-plan-"));
    fs.mkdirSync(path.join(tmp, ".docker-agent"), { recursive: true });
    fs.writeFileSync(path.join(tmp, ".docker-agent", "policies.yaml"), "project: {}");
    stateStore = new StateStore(path.join(tmp, ".docker-agent"));
    composeRunner = new MockComposeRunner(tmp);
  });

  afterEach(() => {
    fs.rmSync(tmp, { recursive: true, force: true });
    process.env.DOCKER_AGENT_BACKEND = prevBackend;
  });

  test("approve plan -> apply succeeds", async () => {
    composeRunner.onBoundRunnerCreated = (runner) => {
      runner.setRunningServices(["web"]);
    };

    const engine = makeEngine({
      tmp,
      stateStore,
      composeRunner,
      providerEvents: [
        planStackEvents({
          stackName: "nginx",
          intent: "tao nginx",
          services: [
            {
              name: "web",
              kind: "custom",
              image: "nginx:1.27-alpine",
              exposure: "public",
              hostPort: 8080,
              containerPort: 80,
            },
          ],
        }),
      ],
    });
    const events: string[] = [];

    for await (const ev of engine.query("tao nginx")) {
      events.push(ev.type);
      if (ev.type === "plan_ready") engine.respondTo(ev.id, { kind: "approve" });
    }

    expect(events).toContain("plan_ready");
    expect(composeRunner.forStackCalls[0]).toMatchObject({
      stackName: "nginx",
      yamlPath: path.join(tmp, "docker-stacks", "nginx.yaml"),
    });
    expect(composeRunner.boundFor("nginx").upCalls[0]).toEqual({ detach: true });
    expect(fs.existsSync(path.join(tmp, "docker-stacks", "nginx.yaml"))).toBe(true);
  });

  test("deny plan -> no apply", async () => {
    const engine = makeEngine({
      tmp,
      stateStore,
      composeRunner,
      providerEvents: [
        planStackEvents({
          stackName: "denied",
          intent: "deny me",
          services: [
            {
              name: "web",
              kind: "custom",
              image: "nginx:1.27",
              exposure: "public",
              hostPort: 8080,
              containerPort: 80,
            },
          ],
        }),
      ],
    });
    let planReadySeen = false;

    for await (const ev of engine.query("deny plan")) {
      if (ev.type === "plan_ready") {
        planReadySeen = true;
        engine.respondTo(ev.id, { kind: "deny" });
      }
    }

    expect(planReadySeen).toBe(true);
    expect(composeRunner.forStackCalls).toHaveLength(0);
  });

  test("invalid spec -> plan blocked, no apply", async () => {
    const engine = makeEngine({
      tmp,
      stateStore,
      composeRunner,
      providerEvents: [
        planStackEvents({
          stackName: "bad",
          intent: "bad spec",
          services: [
            {
              name: "web",
              kind: "custom",
              // missing image -> invalid_spec
            },
          ],
        }),
      ],
    });
    const events: string[] = [];

    for await (const ev of engine.query("bad spec")) {
      events.push(ev.type);
    }

    expect(events).not.toContain("plan_ready");
    expect(composeRunner.forStackCalls).toHaveLength(0);
  });

  test("apply failure -> rollback_started + rollback_result emitted", async () => {
    composeRunner.onBoundRunnerCreated = (runner) => {
      runner.up = async function* () {
        yield "partial failure\n";
        return 1;
      } as never;
      runner.psRows = [{ Name: "partial-web-1", Service: "web", State: "running" }];
    };

    const engine = makeEngine({
      tmp,
      stateStore,
      composeRunner,
      providerEvents: [
        planStackEvents({
          stackName: "partial",
          intent: "deploy partial",
          services: [
            {
              name: "web",
              kind: "custom",
              image: "nginx:1.27",
              exposure: "public",
              hostPort: 8080,
              containerPort: 80,
            },
            {
              name: "db",
              kind: "catalog",
              catalogId: "postgresql:16",
            },
          ],
        }),
        [{ type: "message_stop", stopReason: "end_turn" }],
      ],
    });

    const rollbackEvents: Array<{ type: string; runningServices?: string[] }> = [];

    for await (const ev of engine.query("deploy partial")) {
      if (ev.type === "plan_ready") {
        engine.respondTo(ev.id, { kind: "approve" });
      }
      if (ev.type === "rollback_started" || ev.type === "rollback_result") {
        rollbackEvents.push(ev);
      }
    }

    const started = rollbackEvents.find((e) => e.type === "rollback_started");
    const result = rollbackEvents.find((e) => e.type === "rollback_result");
    expect(started).toBeDefined();
    expect(started?.runningServices).toEqual(["web"]);
    expect(result).toBeDefined();
  });
}, 20_000);
