export type InteractionPhase =
  | "idle"
  | "running"
  | "awaiting_input"
  | "cancelling"
  | "queue_paused";

export interface InteractionState {
  phase: InteractionPhase;
  queue: string[];
  current?: string | undefined;
  turnId: number;
}

export type InteractionAction =
  | { type: "submit"; text: string }
  | { type: "turn_started" }
  | { type: "turn_ended"; cancelled?: boolean; error?: boolean }
  | { type: "awaiting_input" }
  | { type: "input_resolved" }
  | { type: "cancel_current" }
  | { type: "resume_queue" }
  | { type: "remove_queued"; index: number }
  | { type: "clear_queue" }
  | { type: "reset" };

export function interactionReducer(
  state: InteractionState,
  action: InteractionAction,
): InteractionState {
  switch (action.type) {
    case "reset":
      return { phase: "idle", queue: [], current: undefined, turnId: state.turnId + 1 };
    case "submit": {
      if (state.phase === "idle" || state.phase === "queue_paused") {
        return { ...state, phase: "running", current: action.text, turnId: state.turnId + 1 };
      }
      return { ...state, queue: [...state.queue, action.text] };
    }
    case "turn_started": {
      return { ...state, phase: "running" };
    }
    case "turn_ended": {
      if (action.cancelled || action.error || state.phase === "cancelling") {
        return { ...state, phase: "queue_paused", current: undefined };
      }
      if (state.queue.length > 0) {
        const [next, ...rest] = state.queue;
        return { ...state, phase: "running", current: next, queue: rest, turnId: state.turnId + 1 };
      }
      return { ...state, phase: "idle", current: undefined };
    }
    case "awaiting_input": {
      return { ...state, phase: "awaiting_input" };
    }
    case "input_resolved": {
      return { ...state, phase: "running" };
    }
    case "cancel_current": {
      if (state.phase === "running" || state.phase === "awaiting_input") {
        return { ...state, phase: "cancelling" };
      }
      return state;
    }
    case "resume_queue": {
      if (state.queue.length > 0) {
        const [next, ...rest] = state.queue;
        return { ...state, phase: "running", current: next, queue: rest, turnId: state.turnId + 1 };
      }
      return { ...state, phase: "idle" };
    }
    case "remove_queued": {
      if (action.index < 0 || action.index >= state.queue.length) return state;
      const nextQueue = [...state.queue];
      nextQueue.splice(action.index, 1);
      return { ...state, queue: nextQueue };
    }
    case "clear_queue": {
      return { ...state, queue: [] };
    }
    default:
      return state;
  }
}
