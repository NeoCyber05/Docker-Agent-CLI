import type { LoopContext } from "src/loopContext";
import type { PolicyEngine } from "src/policy/PolicyEngine";
import {
  type RemediateDriftInput,
  type RemediateDriftResult,
  remediateDrift,
} from "src/tools/remediateDrift";
import type { LoopEvent } from "src/types/events";
import type { Message } from "src/types/message";
import type { AgentState } from "../state";
import { runApplyWithRollback } from "./applyWithRollback";

export interface RemediateDriftNodeDeps {
  ctx: LoopContext;
  policyEngine: PolicyEngine;
  emit: (ev: LoopEvent) => void;
}

export const remediateDriftNode =
  ({ ctx, policyEngine, emit }: RemediateDriftNodeDeps) =>
  async (state: typeof AgentState.State) => {
    const last = state.messages[state.messages.length - 1];
    if (!last || last.role !== "assistant") return {};

    const call = (
      last.content as Array<{ type: string; id?: string; name?: string; input?: unknown }>
    ).find((b) => b.type === "tool_use" && b.name === "remediate_drift");
    if (!call || !call.id) return {};

    let parsed: RemediateDriftInput;
    try {
      parsed = remediateDrift.inputSchema.parse(call.input);
    } catch (err) {
      const msg = `remediate_drift validation failed: ${(err as Error).message}`;
      return {
        messages: [
          { role: "tool", toolUseId: call.id, content: msg, isError: true } satisfies Message,
        ],
      };
    }

    // Run the remediate_drift tool itself (emits the same tool_call/progress/result
    // sequence as CurrentBackend).
    emit({ type: "tool_call", name: remediateDrift.name, input: parsed });
    const gen = remediateDrift.call(parsed, ctx);
    let result: RemediateDriftResult;
    while (true) {
      const r = await gen.next();
      if (r.done) {
        result = r.value;
        break;
      }
      emit({ type: "tool_progress", msg: r.value.msg });
    }
    emit({ type: "tool_result", name: remediateDrift.name, output: result });

    if (!result.remediable) {
      const msg = `No remediation needed: ${result.reason ?? "unknown"}`;
      return {
        messages: [
          { role: "tool", toolUseId: call.id, content: msg, isError: false } satisfies Message,
        ],
      };
    }

    const violations = policyEngine.evaluate(result.desiredYaml);
    const denyViolations = violations.filter((v) => v.severity === "deny");
    if (denyViolations.length > 0) {
      const msgs = denyViolations.map((v) => `[${v.service}] ${v.rule}: ${v.message}`).join("\n");
      const msg = `Policy violation(s) detected. Remediation is blocked:\n${msgs}`;
      return {
        messages: [
          { role: "tool", toolUseId: call.id, content: msg, isError: true } satisfies Message,
        ],
      };
    }

    const confirm = await ctx.requestConfirm({
      composeYaml: result.desiredYaml,
      diff: result.diff,
    });
    if (confirm.kind !== "approve") {
      const msg = "User declined remediation.";
      return {
        messages: [
          { role: "tool", toolUseId: call.id, content: msg, isError: false } satisfies Message,
        ],
        aborted: true,
      };
    }

    const applyResult = await runApplyWithRollback({
      stackName: parsed.stackName,
      desiredYaml: result.desiredYaml,
      configFiles: [],
      ctx,
      emit,
    });

    let resultMessage = applyResult.resultMessage;
    let fullyClean = applyResult.ok;
    if (result.diff.status === "extra") {
      const orphans = result.diff.serviceDiffs
        .filter((d) => d.desired === null && d.actual !== null)
        .map((d) => d.service);
      if (orphans.length > 0) {
        fullyClean = false;
        resultMessage += ` Remediation not fully clean: ${orphans.length} orphan service(s) remain (${orphans.join(", ")}). Automatic orphan removal is out of scope (future option).`;
      }
    }

    ctx.stateStore.appendHistory({
      ts: new Date().toISOString(),
      sessionId: ctx.sessionId ?? "unknown",
      stackName: parsed.stackName,
      action: "remediate",
      details: { status: result.diff.status, ok: applyResult.ok, fullyClean },
    });

    return {
      messages: [
        {
          role: "tool",
          toolUseId: call.id,
          content: resultMessage,
          isError: !applyResult.ok,
        } satisfies Message,
      ],
    };
  };
