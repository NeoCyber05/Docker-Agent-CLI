import type { Message } from "src/types/message";
import { describe, expect, it } from "vitest";
import {
  type ActivityAction,
  type ActivityState,
  activityReducer,
  projectMessagesToActivities,
} from "../activity";

function makeState(overrides?: Partial<ActivityState>): ActivityState {
  return { items: [], activeToolActivityId: null, ...overrides };
}

describe("activityReducer", () => {
  it("handles tool_call -> progress -> result", () => {
    let state = makeState();
    const callAction: ActivityAction = { type: "tool_call", name: "list_stacks", input: {} };
    state = activityReducer(state, callAction);
    expect(state.items.length).toBe(1);
    const tool = state.items[0] as (typeof state.items)[number];
    expect(tool.type).toBe("tool");
    expect((tool as Extract<typeof tool, { type: "tool" }>).status).toBe("running");
    expect(state.activeToolActivityId).toBe(tool.id);

    state = activityReducer(state, { type: "tool_progress", msg: "Listing stacks..." });
    expect(
      (state.items[0] as Extract<(typeof state.items)[0], { type: "tool" }>).progressMsgs,
    ).toContain("Listing stacks...");

    state = activityReducer(state, {
      type: "tool_result",
      name: "list_stacks",
      output: { stacks: [] },
    });
    expect((state.items[0] as Extract<(typeof state.items)[0], { type: "tool" }>).status).toBe(
      "completed",
    );
    expect(state.activeToolActivityId).toBeNull();
  });

  it("marks explicit unsuccessful tool output as failed", () => {
    let state = activityReducer(makeState(), {
      type: "tool_call",
      name: "apply_stack",
      input: { stackName: "web" },
    });
    state = activityReducer(state, {
      type: "tool_result",
      name: "apply_stack",
      output: { ok: false, exitCode: 1, errorOutput: "compose failed" },
    });

    const tool = state.items[0];
    expect(tool?.type).toBe("tool");
    expect(tool && tool.type === "tool" ? tool.status : undefined).toBe("failed");
  });

  it("bounds combined tool input and output details", () => {
    let state = activityReducer(makeState(), {
      type: "tool_call",
      name: "exec_docker",
      input: { args: ["logs", "container"] },
    });
    state = activityReducer(state, {
      type: "tool_result",
      name: "exec_docker",
      output: Object.fromEntries(Array.from({ length: 20 }, (_, i) => [`field${i}`, `value${i}`])),
    });
    const tool = state.items[0];
    const details = tool?.type === "tool" ? tool.detailLines : [];
    expect(details.length).toBeLessThanOrEqual(20);
    expect(Buffer.byteLength(details.join("\n"), "utf8")).toBeLessThanOrEqual(4096);
  });

  it("sanitizes and bounds tool progress kept in UI state", () => {
    let state = activityReducer(makeState(), {
      type: "tool_call",
      name: "pull_image",
      input: { image: "nginx" },
    });
    for (let index = 0; index < 30; index++) {
      state = activityReducer(state, {
        type: "tool_progress",
        msg: `step ${index} token=very-secret-token ${"x".repeat(300)}`,
      });
    }

    const tool = state.items[0];
    expect(tool?.type).toBe("tool");
    const progress = tool && tool.type === "tool" ? tool.progressMsgs : [];
    expect(progress.length).toBeLessThanOrEqual(20);
    expect(Buffer.byteLength(progress.join("\n"), "utf8")).toBeLessThanOrEqual(4096);
    expect(progress.join("\n")).not.toContain("very-secret-token");
  });

  it("handles tool_call -> error", () => {
    let state = makeState();
    state = activityReducer(state, {
      type: "tool_call",
      name: "exec_docker",
      input: { args: ["ps"] },
    });
    state = activityReducer(state, { type: "tool_error", name: "exec_docker", error: "exit 1" });
    const tool = state.items[0] as Extract<(typeof state.items)[0], { type: "tool" }>;
    expect(tool.status).toBe("failed");
    expect(state.activeToolActivityId).toBeNull();
  });

  it("handles cancellation", () => {
    let state = makeState();
    state = activityReducer(state, {
      type: "tool_call",
      name: "pull_image",
      input: { image: "nginx" },
    });
    state = activityReducer(state, { type: "tool_cancelled" });
    const tool = state.items[0] as Extract<(typeof state.items)[0], { type: "tool" }>;
    expect(tool.status).toBe("cancelled");
    expect(state.activeToolActivityId).toBeNull();
  });

  it("falls back to latest running tool on mismatched result name", () => {
    let state = makeState();
    state = activityReducer(state, {
      type: "tool_call",
      name: "exec_docker",
      input: { args: ["ps"] },
    });
    state = activityReducer(state, { type: "tool_result", name: "unknown_tool", output: {} });
    const tool = state.items[0] as Extract<(typeof state.items)[0], { type: "tool" }>;
    expect(tool.status).toBe("completed");
  });

  it("ignores progress when no active tool", () => {
    let state = makeState();
    state = activityReducer(state, { type: "tool_progress", msg: "orphan" });
    expect(state.items.length).toBe(0);
  });

  it("handles assistant_text delta", () => {
    let state = makeState();
    state = activityReducer(state, { type: "assistant_text", delta: "Hello" });
    expect(state.items.length).toBe(1);
    expect(state.items[0]).toMatchObject({ type: "text", role: "assistant", text: "Hello" });
    state = activityReducer(state, { type: "assistant_text", delta: " world" });
    expect(state.items[0]).toMatchObject({ type: "text", role: "assistant", text: "Hello world" });
  });

  it("handles user text", () => {
    let state = makeState();
    state = activityReducer(state, { type: "user_text", text: "deploy web" });
    expect(state.items[0]).toMatchObject({ type: "text", role: "user", text: "deploy web" });
  });

  it("handles error event", () => {
    let state = makeState();
    state = activityReducer(state, { type: "error", error: new Error("boom") });
    expect(state.items[0]).toMatchObject({ type: "text", role: "error", text: "boom" });
  });

  it("handles usage event", () => {
    let state = makeState();
    state = activityReducer(state, { type: "usage", inputTokens: 10, outputTokens: 20 });
    expect(state.items[0]).toMatchObject({ type: "usage", inputTokens: 10, outputTokens: 20 });
  });

  it("handles rollback_started and rollback_result", () => {
    let state = makeState();
    state = activityReducer(state, {
      type: "rollback_started",
      stackName: "web",
      reason: "apply_failed",
      detail: "exit 1",
    });
    expect(state.items[0]).toMatchObject({
      type: "rollback",
      stackName: "web",
      phase: "started",
      detail: "exit 1",
    });
    state = activityReducer(state, {
      type: "rollback_result",
      stackName: "web",
      ok: true,
      restored: "previous",
    });
    const rollback = state.items[0] as Extract<(typeof state.items)[0], { type: "rollback" }>;
    expect(rollback.phase).toBe("completed");
    expect(rollback.ok).toBe(true);
  });
});

describe("projectMessagesToActivities", () => {
  it("pairs tool_use and tool result by id", () => {
    const messages: Message[] = [
      { role: "user", content: "deploy" },
      {
        role: "assistant",
        content: [
          { type: "text", text: "OK" },
          { type: "tool_use", id: "tu1", name: "plan_stack", input: { stackName: "web" } },
        ],
      },
      { role: "tool", toolUseId: "tu1", content: "planned", isError: false },
    ];
    const activities = projectMessagesToActivities(messages);
    const tool = activities.find((a) => a.type === "tool") as Extract<
      (typeof activities)[number],
      { type: "tool" }
    >;
    expect(tool).toBeDefined();
    expect(tool.name).toBe("plan_stack");
    expect(tool.status).toBe("completed");
    expect(tool.detailLines.length).toBeGreaterThan(0);
  });

  it("marks tool result as failed when isError is true", () => {
    const messages: Message[] = [
      {
        role: "assistant",
        content: [{ type: "tool_use", id: "tu2", name: "exec_docker", input: { args: ["ps"] } }],
      },
      { role: "tool", toolUseId: "tu2", content: "failed", isError: true },
    ];
    const activities = projectMessagesToActivities(messages);
    const tool = activities.find((a) => a.type === "tool") as Extract<
      (typeof activities)[number],
      { type: "tool" }
    >;
    expect(tool.status).toBe("failed");
  });

  it("marks persisted unsuccessful output as failed", () => {
    const messages: Message[] = [
      {
        role: "assistant",
        content: [
          { type: "tool_use", id: "tu3", name: "apply_stack", input: { stackName: "web" } },
        ],
      },
      {
        role: "tool",
        toolUseId: "tu3",
        content: '{"ok":false,"exitCode":1}',
        isError: false,
      },
    ];
    const tool = projectMessagesToActivities(messages).find((activity) => activity.type === "tool");
    expect(tool?.type === "tool" ? tool.status : undefined).toBe("failed");
  });

  it("handles orphaned tool result without tool_use", () => {
    const messages: Message[] = [
      { role: "tool", toolUseId: "tu_missing", content: "result", isError: false },
    ];
    const activities = projectMessagesToActivities(messages);
    expect(activities.some((a) => a.type === "tool")).toBe(true);
  });

  it("includes user and assistant text", () => {
    const messages: Message[] = [
      { role: "user", content: "hello" },
      { role: "assistant", content: [{ type: "text", text: "hi" }] },
    ];
    const activities = projectMessagesToActivities(messages);
    expect(activities[0]).toMatchObject({ type: "text", role: "user", text: "hello" });
    expect(activities[1]).toMatchObject({ type: "text", role: "assistant", text: "hi" });
  });
});
