import type { Message } from "src/types/message";
import { presentTool, sanitizeToolText } from "./toolPresentation";

const MAX_PROGRESS_LINES = 20;
const MAX_PROGRESS_BYTES = 4096;

function boundUiLines(lines: string[]): string[] {
  const bounded = lines
    .flatMap((line) => sanitizeToolText(line).split("\n"))
    .slice(-MAX_PROGRESS_LINES);
  while (Buffer.byteLength(bounded.join("\n"), "utf8") > MAX_PROGRESS_BYTES) {
    bounded.shift();
  }
  return bounded;
}

function outputFailed(output: unknown): boolean {
  if (!output || typeof output !== "object") return false;
  const result = output as Record<string, unknown>;
  return (
    result.ok === false ||
    result.healthy === false ||
    (typeof result.exitCode === "number" && result.exitCode !== 0) ||
    result.status === "error" ||
    result.status === "failed"
  );
}

let _idCounter = 0;
function nextId(): string {
  return `act-${Date.now().toString(36)}-${(_idCounter++).toString(36)}`;
}

export type ToolActivityStatus = "running" | "completed" | "failed" | "cancelled";

export interface ToolActivity {
  id: string;
  type: "tool";
  name: string;
  title: string;
  summary: string;
  status: ToolActivityStatus;
  progressMsgs: string[];
  detailLines: string[];
  startTime: number;
  endTime?: number;
}

export interface TextActivity {
  id: string;
  type: "text";
  role: "user" | "assistant" | "error";
  text: string;
}

export interface UsageActivity {
  id: string;
  type: "usage";
  inputTokens: number;
  outputTokens: number;
}

export interface RollbackActivity {
  id: string;
  type: "rollback";
  stackName: string;
  phase: "started" | "completed";
  ok?: boolean;
  restored?: string;
  detail?: string | undefined;
}

export type ActivityItem = TextActivity | ToolActivity | UsageActivity | RollbackActivity;

export interface ActivityState {
  items: ActivityItem[];
  activeToolActivityId: string | null;
}

export type ActivityAction =
  | { type: "tool_call"; name: string; input: unknown }
  | { type: "tool_progress"; msg: string }
  | { type: "tool_result"; name: string; output: unknown }
  | { type: "tool_error"; name: string; error: string }
  | { type: "tool_cancelled" }
  | { type: "assistant_text"; delta: string }
  | { type: "user_text"; text: string }
  | { type: "error"; error: Error }
  | { type: "replace"; items: ActivityItem[] }
  | { type: "reset" }
  | { type: "usage"; inputTokens: number; outputTokens: number }
  | { type: "rollback_started"; stackName: string; reason: string; detail: string }
  | {
      type: "rollback_result";
      stackName: string;
      ok: boolean;
      restored: string;
      detail?: string | undefined;
    };

export function activityReducer(state: ActivityState, action: ActivityAction): ActivityState {
  const now = Date.now();

  switch (action.type) {
    case "replace":
      return { items: action.items, activeToolActivityId: null };
    case "reset":
      return { items: [], activeToolActivityId: null };
    case "tool_call": {
      const id = nextId();
      const presentation = presentTool(action.name, action.input);
      const tool: ToolActivity = {
        id,
        type: "tool",
        name: action.name,
        title: presentation.title,
        summary: presentation.summary,
        status: "running",
        progressMsgs: [],
        detailLines: [...presentation.detailLines],
        startTime: now,
      };
      return {
        items: [...state.items, tool],
        activeToolActivityId: id,
      };
    }
    case "tool_progress": {
      if (!state.activeToolActivityId) return state;
      return {
        ...state,
        items: state.items.map((item) => {
          if (item.type === "tool" && item.id === state.activeToolActivityId) {
            return { ...item, progressMsgs: boundUiLines([...item.progressMsgs, action.msg]) };
          }
          return item;
        }),
      };
    }
    case "tool_result": {
      const targetId = state.activeToolActivityId;
      if (!targetId) return state;
      const presentation = presentTool(action.name, undefined, action.output);
      return {
        items: state.items.map((item) => {
          if (item.type === "tool" && item.id === targetId) {
            return {
              ...item,
              status: outputFailed(action.output) ? "failed" : "completed",
              detailLines: boundUiLines([...item.detailLines, ...presentation.detailLines]),
              endTime: now,
            };
          }
          return item;
        }),
        activeToolActivityId: null,
      };
    }
    case "tool_error": {
      const targetId = state.activeToolActivityId;
      if (!targetId) return state;
      return {
        items: state.items.map((item) => {
          if (item.type === "tool" && item.id === targetId) {
            return {
              ...item,
              status: "failed",
              detailLines: boundUiLines([...item.detailLines, `Error: ${action.error}`]),
              endTime: now,
            };
          }
          return item;
        }),
        activeToolActivityId: null,
      };
    }
    case "tool_cancelled": {
      const targetId = state.activeToolActivityId;
      if (!targetId) return state;
      return {
        items: state.items.map((item) => {
          if (item.type === "tool" && item.id === targetId) {
            return { ...item, status: "cancelled", endTime: now };
          }
          return item;
        }),
        activeToolActivityId: null,
      };
    }
    case "assistant_text": {
      const last = state.items[state.items.length - 1];
      if (last && last.type === "text" && last.role === "assistant") {
        return {
          ...state,
          items: [...state.items.slice(0, -1), { ...last, text: last.text + action.delta }],
        };
      }
      return {
        ...state,
        items: [
          ...state.items,
          { id: nextId(), type: "text", role: "assistant", text: action.delta },
        ],
      };
    }
    case "user_text": {
      return {
        ...state,
        items: [...state.items, { id: nextId(), type: "text", role: "user", text: action.text }],
      };
    }
    case "error": {
      return {
        ...state,
        items: [
          ...state.items,
          { id: nextId(), type: "text", role: "error", text: action.error.message },
        ],
      };
    }
    case "usage": {
      return {
        ...state,
        items: [
          ...state.items,
          {
            id: nextId(),
            type: "usage",
            inputTokens: action.inputTokens,
            outputTokens: action.outputTokens,
          },
        ],
      };
    }
    case "rollback_started": {
      return {
        ...state,
        items: [
          ...state.items,
          {
            id: nextId(),
            type: "rollback",
            stackName: action.stackName,
            phase: "started",
            detail: action.detail,
          },
        ],
      };
    }
    case "rollback_result": {
      // Find the most recent rollback for this stack without a result and update it,
      // or append a new one if not found.
      let found = false;
      const updated = [...state.items];
      for (let i = updated.length - 1; i >= 0; i--) {
        const item = updated[i];
        if (
          item &&
          item.type === "rollback" &&
          item.stackName === action.stackName &&
          item.phase === "started"
        ) {
          updated[i] = {
            ...item,
            phase: "completed",
            ok: action.ok,
            restored: action.restored,
            detail: action.detail,
          };
          found = true;
          break;
        }
      }
      if (!found) {
        updated.push({
          id: nextId(),
          type: "rollback",
          stackName: action.stackName,
          phase: "completed",
          ok: action.ok,
          restored: action.restored,
          detail: action.detail,
        });
      }
      return { ...state, items: updated };
    }
    default:
      return state;
  }
}

export function projectMessagesToActivities(messages: Message[]): ActivityItem[] {
  const items: ActivityItem[] = [];
  const toolMap = new Map<string, ToolActivity>();

  for (const msg of messages) {
    if (msg.role === "user") {
      items.push({ id: nextId(), type: "text", role: "user", text: msg.content });
    } else if (msg.role === "assistant") {
      for (const block of msg.content) {
        if (block.type === "text") {
          const last = items[items.length - 1];
          if (last && last.type === "text" && last.role === "assistant") {
            last.text += block.text;
          } else {
            items.push({ id: nextId(), type: "text", role: "assistant", text: block.text });
          }
        } else if (block.type === "tool_use") {
          const presentation = presentTool(block.name, block.input);
          const tool: ToolActivity = {
            id: block.id,
            type: "tool",
            name: block.name,
            title: presentation.title,
            summary: presentation.summary,
            status: "running",
            progressMsgs: [],
            detailLines: [...presentation.detailLines],
            startTime: 0,
          };
          items.push(tool);
          toolMap.set(block.id, tool);
        }
      }
    } else if (msg.role === "tool") {
      const existing = toolMap.get(msg.toolUseId);
      let parsedOutput: unknown;
      try {
        parsedOutput = JSON.parse(msg.content);
      } catch {
        parsedOutput = undefined;
      }
      if (existing) {
        existing.status = msg.isError || outputFailed(parsedOutput) ? "failed" : "completed";
        if (msg.isError) {
          existing.detailLines = boundUiLines([...existing.detailLines, `Error: ${msg.content}`]);
        } else {
          if (parsedOutput !== undefined) {
            const presentation = presentTool(existing.name, undefined, parsedOutput);
            existing.detailLines = boundUiLines([
              ...existing.detailLines,
              ...presentation.detailLines,
            ]);
          } else {
            existing.detailLines = boundUiLines([...existing.detailLines, msg.content]);
          }
        }
      } else {
        // orphaned result
        const tool: ToolActivity = {
          id: msg.toolUseId,
          type: "tool",
          name: "unknown",
          title: "Tool result",
          summary: "Orphaned tool result",
          status: msg.isError || outputFailed(parsedOutput) ? "failed" : "completed",
          progressMsgs: [],
          detailLines: [sanitizeToolText(msg.content)],
          startTime: 0,
        };
        items.push(tool);
      }
    }
  }

  return items;
}
