import { describe, expect, it } from "vitest";
import {
  type InteractionAction,
  type InteractionState,
  interactionReducer,
} from "../interactionState";

function makeState(overrides?: Partial<InteractionState>): InteractionState {
  return { phase: "idle", queue: [], current: undefined, turnId: 0, ...overrides };
}

describe("interactionReducer", () => {
  it("starts turn immediately when idle", () => {
    const state = makeState();
    const next = interactionReducer(state, { type: "submit", text: "deploy" });
    expect(next.phase).toBe("running");
    expect(next.current).toBe("deploy");
    expect(next.queue).toHaveLength(0);
  });

  it("queues submit when running", () => {
    let state = makeState({ phase: "running", current: "deploy" });
    state = interactionReducer(state, { type: "submit", text: "status" });
    expect(state.phase).toBe("running");
    expect(state.current).toBe("deploy");
    expect(state.queue).toEqual(["status"]);
  });

  it("runs next queued turn on turn_ended", () => {
    let state = makeState({ phase: "running", current: "deploy", queue: ["status", "logs"] });
    state = interactionReducer(state, { type: "turn_ended" });
    expect(state.phase).toBe("running");
    expect(state.current).toBe("status");
    expect(state.queue).toEqual(["logs"]);
  });

  it("goes idle when turn ends with empty queue", () => {
    let state = makeState({ phase: "running", current: "deploy", queue: [] });
    state = interactionReducer(state, { type: "turn_ended" });
    expect(state.phase).toBe("idle");
    expect(state.current).toBeUndefined();
  });

  it("pauses queue after cancel", () => {
    let state = makeState({ phase: "running", current: "deploy", queue: ["status"] });
    state = interactionReducer(state, { type: "cancel_current" });
    expect(state.phase).toBe("cancelling");
    state = interactionReducer(state, { type: "turn_ended" });
    expect(state.phase).toBe("queue_paused");
    expect(state.queue).toEqual(["status"]);
  });

  it("pauses queue after turn error", () => {
    let state = makeState({ phase: "running", current: "deploy", queue: ["status"] });
    state = interactionReducer(state, { type: "turn_ended", error: true });
    expect(state.phase).toBe("queue_paused");
    expect(state.queue).toEqual(["status"]);
  });

  it("resumes queue and dequeues next", () => {
    let state = makeState({ phase: "queue_paused", current: undefined, queue: ["status", "logs"] });
    state = interactionReducer(state, { type: "resume_queue" });
    expect(state.phase).toBe("running");
    expect(state.current).toBe("status");
    expect(state.queue).toEqual(["logs"]);
  });

  it("resumes to idle when queue empty", () => {
    let state = makeState({ phase: "queue_paused", queue: [] });
    state = interactionReducer(state, { type: "resume_queue" });
    expect(state.phase).toBe("idle");
  });

  it("removeQueued removes by index", () => {
    let state = makeState({ phase: "running", current: "deploy", queue: ["a", "b", "c"] });
    state = interactionReducer(state, { type: "remove_queued", index: 1 });
    expect(state.queue).toEqual(["a", "c"]);
  });

  it("ignores an invalid queue index", () => {
    const state = makeState({ phase: "running", current: "deploy", queue: ["a", "b"] });
    expect(interactionReducer(state, { type: "remove_queued", index: -1 }).queue).toEqual([
      "a",
      "b",
    ]);
    expect(interactionReducer(state, { type: "remove_queued", index: 2 }).queue).toEqual([
      "a",
      "b",
    ]);
  });

  it("clearQueue empties queue", () => {
    let state = makeState({ phase: "running", current: "deploy", queue: ["a", "b"] });
    state = interactionReducer(state, { type: "clear_queue" });
    expect(state.queue).toHaveLength(0);
  });

  it("awaits_input sets phase", () => {
    let state = makeState({ phase: "running", current: "deploy" });
    state = interactionReducer(state, { type: "awaiting_input" });
    expect(state.phase).toBe("awaiting_input");
  });

  it("input_resolved returns to running", () => {
    let state = makeState({ phase: "awaiting_input", current: "deploy" });
    state = interactionReducer(state, { type: "input_resolved" });
    expect(state.phase).toBe("running");
  });

  it("new turn after abort starts fresh", () => {
    let state = makeState({ phase: "queue_paused", queue: [] });
    state = interactionReducer(state, { type: "submit", text: "new" });
    expect(state.phase).toBe("running");
    expect(state.current).toBe("new");
  });

  it("maintains FIFO ordering across multiple queued submits", () => {
    let state = makeState({ phase: "running", current: "first" });
    state = interactionReducer(state, { type: "submit", text: "second" });
    state = interactionReducer(state, { type: "submit", text: "third" });
    expect(state.queue).toEqual(["second", "third"]);
    state = interactionReducer(state, { type: "turn_ended" });
    expect(state.current).toBe("second");
    state = interactionReducer(state, { type: "turn_ended" });
    expect(state.current).toBe("third");
    state = interactionReducer(state, { type: "turn_ended" });
    expect(state.phase).toBe("idle");
  });
});
