import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { QueryEngine } from "src/QueryEngine";
import type { CallModelParams, ProviderEvent } from "src/services/api/types";
import { SessionStore } from "src/state/SessionStore";
import { StateStore } from "src/state/StateStore";
import type { StackDefinition } from "src/types/stack";
import { afterEach, beforeEach, describe, expect, test } from "vitest";
import { MockComposeRunner } from "../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../tests/mocks/mockDockerEngine";

function fakeProvider(events: ProviderEvent[]) {
  return {
    name: "fake",
    stream: async function* () {
      for (const ev of events) yield ev;
    },
  };
}

function recordingProvider(events: ProviderEvent[], calls: CallModelParams[]) {
  return {
    name: "recording",
    stream: async function* (params: CallModelParams) {
      calls.push(params);
      for (const ev of events) yield ev;
    },
  };
}

describe("QueryEngine", () => {
  let tmp: string;
  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "qe-"));
    fs.writeFileSync(path.join(tmp, "project-policies.yaml"), "project: {}");
  });
  afterEach(() => {
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  test("query is reusable across multiple turns", async () => {
    const engine = new QueryEngine({
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      cwd: tmp,
      provider: fakeProvider([
        { type: "text_delta", text: "first" },
        { type: "message_stop", stopReason: "end_turn" },
      ]),
    });

    const turn1: string[] = [];
    for await (const ev of engine.query("hi")) {
      if (ev.type === "assistant_text") turn1.push(ev.delta);
    }
    expect(turn1.join("")).toBe("first");

    engine.provider = fakeProvider([
      { type: "text_delta", text: "second" },
      { type: "message_stop", stopReason: "end_turn" },
    ]);

    const turn2: string[] = [];
    for await (const ev of engine.query("again")) {
      if (ev.type === "assistant_text") turn2.push(ev.delta);
    }
    expect(turn2.join("")).toBe("second");
  });

  test("respondTo resolves a pending permission request", async () => {
    const engine = new QueryEngine({
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      cwd: tmp,
      provider: fakeProvider([
        { type: "tool_use_start", id: "t1", name: "pull_image" },
        { type: "tool_use_delta", id: "t1", argsPartialJson: '{"image":"nginx"}' },
        { type: "tool_use_stop", id: "t1" },
        { type: "message_stop", stopReason: "tool_use" },
      ]),
    });

    const collected: string[] = [];
    const done = (async () => {
      for await (const ev of engine.query("pull nginx")) {
        if (ev.type === "permission_request") {
          engine.respondTo(ev.id, { kind: "approve" });
        }
        collected.push(ev.type);
      }
    })();
    await done;
    expect(collected).toContain("permission_request");
    expect(collected).toContain("tool_result");
  });

  test("respondTo returns false for unknown id", () => {
    const engine = new QueryEngine({
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      cwd: tmp,
      provider: fakeProvider([]),
    });
    expect(engine.respondTo("nonexistent", { kind: "approve" })).toBe(false);
  });

  test("passes the active model override to the provider", async () => {
    const calls: CallModelParams[] = [];
    const engine = new QueryEngine({
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      cwd: tmp,
      provider: recordingProvider(
        [
          { type: "text_delta", text: "ok" },
          { type: "message_stop", stopReason: "end_turn" },
        ],
        calls,
      ),
      model: "gpt-4.1-mini",
    });

    for await (const _ of engine.query("hello")) {
      // drain
    }

    expect(calls).toHaveLength(1);
    expect(calls[0]?.model).toBe("gpt-4.1-mini");
  });

  test("abort marks the active controller as aborted", async () => {
    const engine = new QueryEngine({
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      cwd: tmp,
      provider: fakeProvider([
        { type: "text_delta", text: "hello" },
        { type: "message_stop", stopReason: "end_turn" },
      ]),
    });

    const iter = engine.query("test");
    const first = await iter.next();
    expect(first.done).toBe(false);
    const ctrl = (engine as unknown as { activeController: AbortController | null })
      .activeController;
    expect(ctrl).not.toBeNull();
    engine.abort();
    expect(ctrl?.signal.aborted).toBe(true);
    // drain
    for await (const _ of iter) {
      // noop
    }
  });

  test("passes the active abort signal to the provider", async () => {
    const calls: CallModelParams[] = [];
    const engine = new QueryEngine({
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      cwd: tmp,
      provider: recordingProvider([{ type: "message_stop", stopReason: "end_turn" }], calls),
    });

    for await (const _ of engine.query("hello")) {
      // drain
    }

    expect(calls[0]?.signal).toBeInstanceOf(AbortSignal);
  });

  test("abort resolves a pending permission request and ends the turn", async () => {
    const engine = new QueryEngine({
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      cwd: tmp,
      provider: fakeProvider([
        { type: "tool_use_start", id: "t1", name: "pull_image" },
        { type: "tool_use_delta", id: "t1", argsPartialJson: '{"image":"nginx"}' },
        { type: "tool_use_stop", id: "t1" },
        { type: "message_stop", stopReason: "tool_use" },
      ]),
    });

    const seen: string[] = [];
    const done = (async () => {
      for await (const event of engine.query("pull nginx")) {
        seen.push(event.type);
        if (event.type === "permission_request") engine.abort();
      }
    })();

    await expect(
      Promise.race([
        done.then(() => "done"),
        new Promise<string>((resolve) => setTimeout(() => resolve("timeout"), 100)),
      ]),
    ).resolves.toBe("done");
    expect(seen).toContain("permission_request");
  });

  test("each query gets a fresh abort controller", async () => {
    const engine = new QueryEngine({
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      cwd: tmp,
      provider: fakeProvider([
        { type: "text_delta", text: "first" },
        { type: "message_stop", stopReason: "end_turn" },
      ]),
    });

    for await (const _ of engine.query("turn1")) {
      // drain
    }
    // After first query ends, activeController should be null
    expect((engine as unknown as { activeController: unknown }).activeController).toBeNull();

    engine.provider = fakeProvider([
      { type: "text_delta", text: "second" },
      { type: "message_stop", stopReason: "end_turn" },
    ]);
    const events: string[] = [];
    for await (const ev of engine.query("turn2")) {
      if (ev.type === "assistant_text") events.push(ev.delta);
    }
    expect(events.join("")).toBe("second");
  });

  test("loadSession restores model and returns cwd mismatch warning", () => {
    const engine = new QueryEngine({
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      cwd: "/current",
      provider: fakeProvider([]),
      model: "cli-default",
    });

    const warning = engine.loadSession({
      schemaVersion: 1,
      id: "saved-session",
      createdAt: "2026-01-01T00:00:00.000Z",
      updatedAt: "2026-01-02T00:00:00.000Z",
      cwd: "/saved",
      provider: "openai",
      model: "gpt-4.1-mini",
      firstPrompt: "hello",
      stackNames: [],
      messages: [{ role: "user", content: "hello" }],
    });

    expect(warning).toContain("/saved");
    expect(engine.sessionId).toBe("saved-session");
    expect(engine.model).toBe("gpt-4.1-mini");
    expect(engine.isResumed).toBe(true);
  });

  test("persists createdAt, model, and stackNames across turns", async () => {
    const stateRoot = path.join(tmp, "state");
    const stateStore = new StateStore(stateRoot);
    const sessionStore = new SessionStore(stateRoot);
    const stackDef: StackDefinition = {
      "x-docker-agent": {
        name: "web",
        createdAt: "2026-01-01T00:00:00.000Z",
        lastApplied: null,
        intent: "test",
        provider: "gemini",
        generatedBy: "test",
        envFileSources: {},
      },
      services: { app: { image: "nginx" } },
    };
    const engine = new QueryEngine({
      stateStore,
      sessionStore,
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      cwd: tmp,
      provider: fakeProvider([
        { type: "text_delta", text: "ok" },
        { type: "message_stop", stopReason: "end_turn" },
      ]),
      model: "gemini-2.0",
    });
    stateStore.write("web", stackDef);

    for await (const _ of engine.query("deploy")) {
      // drain
    }

    const sessionId = engine.sessionId;
    const afterFirst = sessionStore.read(sessionId);
    const createdAt = afterFirst?.createdAt;
    expect(createdAt).toBeTruthy();

    engine.provider = fakeProvider([
      { type: "text_delta", text: "again" },
      { type: "message_stop", stopReason: "end_turn" },
    ]);
    for await (const _ of engine.query("update")) {
      // drain
    }

    const saved = sessionStore.read(sessionId);
    expect(saved?.model).toBe("gemini-2.0");
    expect(saved?.stackNames).toEqual(["web"]);
    expect(saved?.createdAt).toBe(createdAt);
    expect(saved?.updatedAt).not.toBe(createdAt);
  });

  test("reset clears messages and allow set", async () => {
    const engine = new QueryEngine({
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      cwd: tmp,
      provider: fakeProvider([
        { type: "text_delta", text: "hello" },
        { type: "message_stop", stopReason: "end_turn" },
      ]),
    });
    for await (const _ of engine.query("test")) {
      // drain
    }
    engine.reset();
    expect((engine as unknown as { messages: unknown[] }).messages).toHaveLength(0);
  });
});
