import type { Tool, ToolProgress } from "src/Tool";
import type { LoopContext } from "src/loopContext";
import { captureKnownGood, planRollback } from "src/state/rollback";
import { applyStack } from "src/tools/applyStack";
import { destroyStack } from "src/tools/destroyStack";
import {
  type ConfigFileSnapshot,
  type StagedConfigFile,
  restoreConfigFiles,
  snapshotConfigFiles,
  writeConfigFiles,
} from "src/tools/shared/configFiles";
import type { LoopEvent } from "src/types/events";

export interface ApplyWithRollbackParams {
  stackName: string;
  desiredYaml: string;
  scaleOverrides?: Record<string, number>;
  configFiles: StagedConfigFile[];
  ctx: LoopContext;
  emit: (ev: LoopEvent) => void;
}

export interface ApplyWithRollbackResult {
  ok: boolean;
  resultMessage: string;
}

async function runApplyTool<TIn, TOut>(
  tool: Tool<TIn, TOut>,
  input: TIn,
  ctx: LoopContext,
  emit: (ev: LoopEvent) => void,
): Promise<TOut> {
  emit({ type: "tool_call", name: tool.name, input });
  const gen = tool.call(input, ctx);
  let result: TOut;
  while (true) {
    const r = await gen.next();
    if (r.done) {
      result = r.value;
      break;
    }
    emit({ type: "tool_progress", msg: (r.value as ToolProgress).msg });
  }
  emit({ type: "tool_result", name: tool.name, output: result });
  return result;
}

export async function runApplyWithRollback(
  params: ApplyWithRollbackParams,
): Promise<ApplyWithRollbackResult> {
  const { stackName, desiredYaml, scaleOverrides, configFiles, ctx, emit } = params;

  // Capture known-good state BEFORE applyStack overwrites on-disk state
  const known = captureKnownGood(stackName, ctx);

  // Write the agent-authored config files referenced by bind mounts, snapshotting
  // prior state so a failed apply can be rolled back. Confined to ctx.cwd.
  const configSnapshots: ConfigFileSnapshot[] = snapshotConfigFiles(ctx.cwd, configFiles);
  try {
    writeConfigFiles(ctx.cwd, configFiles);
  } catch (err) {
    restoreConfigFiles(configSnapshots);
    return {
      ok: false,
      resultMessage: `failed to write config files: ${(err as Error).message}`,
    };
  }

  const applyInput = applyStack.inputSchema.parse({
    stackName,
    composeYaml: desiredYaml,
    ...(scaleOverrides && Object.keys(scaleOverrides).length ? { scaleOverrides } : {}),
  });
  const applyResult = await runApplyTool(applyStack, applyInput, ctx, emit);

  if (applyResult.ok) {
    return { ok: true, resultMessage: "Stack applied." };
  }

  // Determine failure reason
  const reason = applyResult.healthy === false ? "unhealthy" : "apply_failed";
  const logsTail = applyResult.errorOutput ? `\nRecent logs:\n${applyResult.errorOutput}` : "";
  const detail =
    reason === "unhealthy"
      ? `unhealthy: ${(applyResult.unhealthyServices ?? []).join(", ")}${logsTail}`
      : `exit ${applyResult.exitCode}: ${applyResult.errorOutput ?? "unknown"}`;

  emit({
    type: "rollback_started",
    stackName,
    reason,
    detail,
    ...(applyResult.runningServices ? { runningServices: applyResult.runningServices } : {}),
  });

  const plan = planRollback(known, stackName);
  let restored: "previous" | "removed" | "none" = "none";
  let rollbackOk = true;

  try {
    if (plan.strategy === "restore_previous") {
      // UPDATE with recoverable prior -> re-apply it
      const restoreInput = applyStack.inputSchema.parse({
        stackName,
        composeYaml: plan.composeYaml,
      });
      const restore = await runApplyTool(applyStack, restoreInput, ctx, emit);
      rollbackOk = restore.ok;
      restored = "previous";
    } else if (plan.strategy === "teardown_partial") {
      // FIRST-TIME CREATE -> tear down partial stack
      const downInput = destroyStack.inputSchema.parse({ stackName });
      const down = await runApplyTool(destroyStack, downInput, ctx, emit);
      rollbackOk = down.ok;
      restored = "removed";
    } else {
      // UPDATE expected but unrecoverable -> abort, do NOT modify on-disk state
      rollbackOk = false;
      restored = "none";
    }
  } catch {
    rollbackOk = false;
  }

  restoreConfigFiles(configSnapshots);

  ctx.stateStore.appendHistory({
    ts: new Date().toISOString(),
    sessionId: ctx.sessionId ?? "unknown",
    stackName,
    action: "rollback",
    details: { reason, restored, rollbackOk },
  });

  emit({
    type: "rollback_result",
    stackName,
    ok: rollbackOk,
    restored,
    ...(!rollbackOk ? { detail: "manual intervention may be required" } : {}),
  });

  return {
    ok: false,
    resultMessage: `apply failed (${detail}); rollback ${rollbackOk ? "succeeded" : "FAILED"} (${restored}).`,
  };
}
