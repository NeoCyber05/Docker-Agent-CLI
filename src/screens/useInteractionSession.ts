import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import type { QueryEngine } from "src/QueryEngine";
import type { LoopEvent } from "src/types/events";
import type { Message } from "src/types/message";
import type { PermissionResponse } from "src/types/permissions";
import { activityReducer, projectMessagesToActivities } from "src/ui/activity";
import { interactionReducer } from "src/ui/interactionState";

export function useInteractionSession(
  engine: QueryEngine,
  initialMessages: readonly Message[] = engine.getMessages(),
) {
  const [interaction, dispatchInteraction] = useReducer(interactionReducer, {
    phase: "idle",
    queue: [],
    turnId: 0,
  });
  const [activityState, dispatchActivity] = useReducer(
    activityReducer,
    initialMessages,
    (messages) => ({
      items: projectMessagesToActivities([...messages]),
      activeToolActivityId: null,
    }),
  );
  const [pendingEvent, setPendingEvent] = useState<LoopEvent | null>(null);
  const startedTurnRef = useRef(0);

  const runTurn = useCallback(
    async (text: string) => {
      dispatchActivity({ type: "user_text", text });
      let turnErrored = false;
      try {
        for await (const ev of engine.query(text)) {
          switch (ev.type) {
            case "assistant_text":
              dispatchActivity({ type: "assistant_text", delta: ev.delta });
              break;
            case "tool_call":
              dispatchActivity({ type: "tool_call", name: ev.name, input: ev.input });
              break;
            case "tool_progress":
              dispatchActivity({ type: "tool_progress", msg: ev.msg });
              break;
            case "tool_result":
              dispatchActivity({ type: "tool_result", name: ev.name, output: ev.output });
              break;
            case "error":
              turnErrored = true;
              dispatchActivity({ type: "tool_error", name: "active", error: ev.error.message });
              dispatchActivity({ type: "error", error: ev.error });
              break;
            case "usage":
              dispatchActivity({
                type: "usage",
                inputTokens: ev.inputTokens,
                outputTokens: ev.outputTokens,
              });
              break;
            case "rollback_started":
              dispatchActivity({
                type: "rollback_started",
                stackName: ev.stackName,
                reason: ev.reason,
                detail: ev.detail,
              });
              break;
            case "rollback_result":
              dispatchActivity({
                type: "rollback_result",
                stackName: ev.stackName,
                ok: ev.ok,
                restored: ev.restored,
                detail: ev.detail,
              });
              break;
            case "permission_request":
            case "plan_ready":
            case "typed_confirm_request":
            case "secrets_input_request":
              dispatchInteraction({ type: "awaiting_input" });
              setPendingEvent(ev);
              break;
          }
        }
        dispatchInteraction({ type: "turn_ended", ...(turnErrored ? { error: true } : {}) });
      } catch (err) {
        dispatchActivity({
          type: "error",
          error: err instanceof Error ? err : new Error(String(err)),
        });
        dispatchInteraction({ type: "turn_ended", error: true });
      }
    },
    [engine],
  );

  // A monotonic turn id lets identical queued prompts run sequentially.
  useEffect(() => {
    if (
      interaction.phase === "running" &&
      interaction.current &&
      interaction.turnId !== startedTurnRef.current
    ) {
      startedTurnRef.current = interaction.turnId;
      void runTurn(interaction.current);
    }
  }, [interaction.phase, interaction.current, interaction.turnId, runTurn]);

  const submit = useCallback((text: string) => {
    dispatchInteraction({ type: "submit", text });
  }, []);

  const cancelCurrent = useCallback(() => {
    engine.abort();
    dispatchInteraction({ type: "cancel_current" });
    dispatchActivity({ type: "tool_cancelled" });
    setPendingEvent(null);
  }, [engine]);

  const respond = useCallback(
    (id: string, answer: PermissionResponse) => {
      engine.respondTo(id, answer);
      dispatchInteraction({ type: "input_resolved" });
      setPendingEvent(null);
    },
    [engine],
  );

  const resumeQueue = useCallback(() => {
    dispatchInteraction({ type: "resume_queue" });
  }, []);

  const removeQueued = useCallback((index: number) => {
    dispatchInteraction({ type: "remove_queued", index });
  }, []);

  const clearQueue = useCallback(() => {
    dispatchInteraction({ type: "clear_queue" });
  }, []);

  const replaceActivities = useCallback((messages: readonly Message[]) => {
    dispatchActivity({ type: "replace", items: projectMessagesToActivities([...messages]) });
  }, []);

  const reset = useCallback(() => {
    engine.reset();
    setPendingEvent(null);
    startedTurnRef.current = -1;
    dispatchInteraction({ type: "reset" });
    dispatchActivity({ type: "reset" });
  }, [engine]);

  return {
    phase: interaction.phase,
    queue: interaction.queue,
    activities: activityState.items,
    activeToolActivityId: activityState.activeToolActivityId,
    pendingEvent,
    submit,
    cancelCurrent,
    respond,
    resumeQueue,
    removeQueued,
    clearQueue,
    replaceActivities,
    reset,
    dispatchActivity,
  };
}
