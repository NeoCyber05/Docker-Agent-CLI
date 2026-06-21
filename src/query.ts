import type { LoopContext } from "src/loopContext";
import type { Provider } from "src/services/api/types";
import { captureKnownGood, planRollback } from "src/state/rollback";
import { scrubLine } from "src/state/secretRedactor";
import type { LoopEvent } from "src/types/events";
import type { AssistantBlock, Message } from "src/types/message";
import { type Tool, findToolByName } from "./Tool";
import { buildSystemPrompt, classifyIntent } from "./context";
import { isDestroyAllPrompt, parseDirectDestroyStack } from "./slashDispatch";
import { type QueryMode, getToolsForMode } from "./tools";
import { applyStack } from "./tools/applyStack";
import { destroyAllStacks } from "./tools/destroyAllStacks";
import { destroyStack } from "./tools/destroyStack";
import { type PlanStackResultBlocked, planStack } from "./tools/planStack";
import { remediateDrift } from "./tools/remediateDrift";
import {
  type ConfigFileSnapshot,
  type StagedConfigFile,
  restoreConfigFiles,
  snapshotConfigFiles,
  writeConfigFiles,
} from "./tools/shared/configFiles";
import { collectSecretKeys } from "./tools/shared/secretKeys";
import * as path from "node:path";
import * as fs from "node:fs";
import { PolicyEngine } from "./policy/PolicyEngine";
import { loadUserConfig } from "./config";

export interface QueryParams {
  messages: Message[];
  ctx: LoopContext;
  provider: Provider;
  model?: string;
}

interface CollectedToolUse {
  id: string;
  name: string;
  argsPartial: string;
}

interface ProviderTurnResult {
  text: string;
  toolUses: CollectedToolUse[];
  stopReason: "end_turn" | "tool_use" | "max_tokens";
}

const LOOP_LIMITS: Record<QueryMode, number> = {
  deploy: 16,
  react: 24,
};

async function* runProvider(
  provider: Provider,
  messages: Message[],
  mode: QueryMode,
  ctx: LoopContext,
  model: string | undefined,
): AsyncGenerator<LoopEvent, ProviderTurnResult> {
  const tools = getToolsForMode(mode);
  const system = buildSystemPrompt(mode, ctx.stateStore.summary());
  const provEvents = provider.stream({
    messages,
    tools: tools.map((t) => ({
      name: t.name,
      description: t.description,
      inputSchema: t.inputSchema,
    })),
    system,
    ...(model ? { model } : {}),
    signal: ctx.abortSignal,
  });
  let text = "";
  const toolUses: CollectedToolUse[] = [];
  for await (const ev of provEvents) {
    if (ctx.abortSignal.aborted) return { text, toolUses, stopReason: "end_turn" };
    switch (ev.type) {
      case "text_delta":
        text += ev.text;
        yield { type: "assistant_text", delta: ev.text };
        break;
      case "tool_use_start":
        toolUses.push({ id: ev.id, name: ev.name, argsPartial: "" });
        break;
      case "tool_use_delta": {
        const u = toolUses.find((t) => t.id === ev.id);
        if (u) u.argsPartial += ev.argsPartialJson;
        break;
      }
      case "tool_use_stop":
        break;
      case "error":
        yield { type: "error", error: ev.error };
        return { text, toolUses, stopReason: "end_turn" };
      case "message_stop":
        return { text, toolUses, stopReason: ev.stopReason };
      case "usage":
        yield {
          type: "usage",
          inputTokens: ev.inputTokens,
          outputTokens: ev.outputTokens,
        };
        break;
    }
  }
  return { text, toolUses, stopReason: "end_turn" };
}

async function* runTool<TIn, TOut>(
  tool: Tool<TIn, TOut>,
  input: TIn,
  ctx: LoopContext,
): AsyncGenerator<LoopEvent, TOut> {
  yield { type: "tool_call", name: tool.name, input };
  const gen = tool.call(input, ctx);
  let result: TOut;
  while (true) {
    const r = await gen.next();
    if (r.done) {
      result = r.value;
      break;
    }
    yield { type: "tool_progress", msg: r.value.msg };
  }
  yield { type: "tool_result", name: tool.name, output: result };
  return result;
}

function assistantBlocksFromCollected(
  text: string,
  toolUses: CollectedToolUse[],
): AssistantBlock[] {
  const blocks: AssistantBlock[] = [];
  if (text) blocks.push({ type: "text", text });
  for (const tu of toolUses) {
    let input: unknown = {};
    try {
      input = JSON.parse(tu.argsPartial || "{}");
    } catch {
      /* keep {} */
    }
    blocks.push({ type: "tool_use", id: tu.id, name: tu.name, input });
  }
  return blocks;
}

async function* applyWithRollback(
  stackName: string,
  desiredYaml: string,
  scaleOverrides: Record<string, number> | undefined,
  configFiles: StagedConfigFile[],
  ctx: LoopContext,
): AsyncGenerator<LoopEvent, { ok: boolean; resultMessage: string }> {
  // Capture known-good state BEFORE applyStack overwrites on-disk state
  const known = captureKnownGood(stackName, ctx);

  // Write the agent-authored config files referenced by bind mounts, snapshotting
  // prior state so a failed apply can be rolled back. Confined to ctx.cwd.
  const configSnapshots: ConfigFileSnapshot[] = snapshotConfigFiles(ctx.cwd, configFiles);
  try {
    writeConfigFiles(ctx.cwd, configFiles);
  } catch (err) {
    restoreConfigFiles(configSnapshots);
    return { ok: false, resultMessage: `failed to write config files: ${(err as Error).message}` };
  }

  const applyResult = yield* runTool(
    applyStack,
    {
      stackName,
      composeYaml: desiredYaml,
      ...(scaleOverrides && Object.keys(scaleOverrides).length ? { scaleOverrides } : {}),
    },
    ctx,
  );

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

  yield {
    type: "rollback_started",
    stackName,
    reason,
    detail,
    ...(applyResult.runningServices ? { runningServices: applyResult.runningServices } : {}),
  };

  const plan = planRollback(known, stackName);
  let restored: "previous" | "removed" | "none" = "none";
  let rollbackOk = true;

  try {
    if (plan.strategy === "restore_previous") {
      // UPDATE with recoverable prior → re-apply it
      const restore = yield* runTool(applyStack, { stackName, composeYaml: plan.composeYaml }, ctx);
      rollbackOk = restore.ok;
      restored = "previous";
    } else if (plan.strategy === "teardown_partial") {
      // FIRST-TIME CREATE → tear down partial stack
      const down = yield* runTool(destroyStack, { stackName }, ctx);
      rollbackOk = (down as { ok?: boolean }).ok ?? true;
      restored = "removed";
    } else {
      // UPDATE expected but unrecoverable → abort, do NOT modify on-disk state
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

  yield {
    type: "rollback_result",
    stackName,
    ok: rollbackOk,
    restored,
    ...(!rollbackOk ? { detail: "manual intervention may be required" } : {}),
  };

  return {
    ok: false,
    resultMessage: `apply failed (${detail}); rollback ${rollbackOk ? "succeeded" : "FAILED"} (${restored}).`,
  };
}

function formatPlanBlocker(result: PlanStackResultBlocked): string {
  switch (result.reason) {
    case "invalid_spec":
      return `plan_stack blocked: ${JSON.stringify(result.issues)}`;
    case "invalid_dependency":
      return `plan_stack blocked: ${JSON.stringify(result.dependency)}`;
    case "port_conflict":
      return `plan_stack blocked: ${JSON.stringify(result.portCheck)}`;
    case "missing_config_file":
      return `plan_stack blocked: ${JSON.stringify(result.missingFiles)}`;
    case "missing_required_env":
      return `plan_stack blocked: ${JSON.stringify(result.missingByService)}`;
    case "resource_limit":
      return `plan_stack blocked: ${JSON.stringify(result.issues)}`;
    case "db_port_exposed":
      return `plan_stack blocked: ${JSON.stringify(result.issues)}`;
    case "unsafe_volume":
      return `plan_stack blocked: ${JSON.stringify(result.issues)}`;
    case "undeclared_network":
      return `plan_stack blocked: ${JSON.stringify(result.issues)}`;
    case "invalid_yaml":
      return `plan_stack blocked: ${result.error}`;
  }
}

async function* handlePlanStackToolUse(
  tu: CollectedToolUse,
  ctx: LoopContext,
  policyEngine: PolicyEngine,
): AsyncGenerator<LoopEvent, { isError: boolean; resultMessage: string; userDeclined?: boolean }> {
  let parsed: unknown = (() => {
    try {
      return planStack.inputSchema.parse(JSON.parse(tu.argsPartial || "{}"));
    } catch (err) {
      return { _error: (err as Error).message };
    }
  })();

  while (true) {
    if ((parsed as { _error?: string })._error) {
      return {
        isError: true,
        resultMessage: `plan_stack validation failed: ${(parsed as { _error: string })._error}`,
      };
    }
    const reParsed = planStack.inputSchema.parse(parsed);
    const planResult = yield* runTool(planStack, reParsed, ctx);
    if (planResult.blocked) {
      if (
        planResult.reason === "invalid_spec" ||
        planResult.reason === "invalid_dependency" ||
        planResult.reason === "port_conflict" ||
        planResult.reason === "resource_limit" ||
        planResult.reason === "db_port_exposed" ||
        planResult.reason === "unsafe_volume" ||
        planResult.reason === "undeclared_network" ||
        planResult.reason === "invalid_yaml"
      ) {
        return { isError: true, resultMessage: formatPlanBlocker(planResult) };
      }
      if (planResult.reason === "missing_config_file") {
        const paths = planResult.missingFiles.join(", ");
        return {
          isError: true,
          resultMessage: `Missing content for bind-mounted config file(s): ${paths}. Re-run plan_stack including each path in the configFiles map with its full content.`,
        };
      }
      const injected: Record<string, string[]> = planResult.missingByService;
      for (const [service, keys] of Object.entries(injected)) {
        const resp = yield* requestSecretsAndPatch(service, keys, ctx, parsed as never);
        if (resp === null) {
          return { isError: false, resultMessage: "User cancelled secrets input." };
        }
        parsed = resp.patchedInput as typeof parsed;
      }
      continue;
    }

    // Redact secret-looking values from config-file content for display only;
    // applyWithRollback writes the real planResult.configFiles content.
    const secretKeys = collectSecretKeys((parsed as { stackName: string }).stackName, {
      cwd: ctx.cwd,
      stateStore: ctx.stateStore,
    });

    const violations = policyEngine.evaluate(planResult.composeYaml);
    const denyViolations = violations.filter((v) => v.severity === "deny");
    if (denyViolations.length > 0) {
      const msgs = denyViolations
        .map((v) => `[${v.service}] ${v.rule}: ${v.message}`)
        .join("\n");
      return {
        isError: true,
        resultMessage: `Policy violation(s) detected. Deployment is blocked:\n${msgs}`,
      };
    }

    const confirm = await ctx.requestConfirm({
      composeYaml: planResult.composeYaml,
      diff: planResult.diff,
      hash: planResult.hash,
      ...(planResult.autoGeneratedSecrets.length
        ? { autoGeneratedSecrets: planResult.autoGeneratedSecrets }
        : {}),
      ...(planResult.configFiles.length
        ? {
            configFiles: planResult.configFiles.map((f) => ({
              path: f.path,
              content: f.content
                .split("\n")
                .map((line) => scrubLine(line, secretKeys))
                .join("\n"),
              bytes: f.bytes,
            })),
          }
        : {}),
    });
    if (confirm.kind !== "approve") {
      return { isError: false, resultMessage: "User declined plan.", userDeclined: true };
    }
    const r = yield* applyWithRollback(
      (parsed as { stackName: string }).stackName,
      planResult.composeYaml,
      Object.keys(planResult.scaleOverrides).length ? planResult.scaleOverrides : undefined,
      planResult.configFiles,
      ctx,
    );
    return { isError: !r.ok, resultMessage: r.resultMessage };
  }
}

async function* handleRemediateDriftToolUse(
  tu: CollectedToolUse,
  ctx: LoopContext,
  policyEngine: PolicyEngine,
): AsyncGenerator<LoopEvent, { isError: boolean; resultMessage: string; userDeclined?: boolean }> {
  let parsed: ReturnType<typeof remediateDrift.inputSchema.parse>;
  try {
    parsed = remediateDrift.inputSchema.parse(JSON.parse(tu.argsPartial || "{}"));
  } catch (err) {
    return {
      isError: true,
      resultMessage: `remediate_drift validation failed: ${(err as Error).message}`,
    };
  }

  const result = yield* runTool(remediateDrift, parsed, ctx);

  if (!result.remediable) {
    return {
      isError: false,
      resultMessage: `No remediation needed: ${result.reason ?? "unknown"}`,
    };
  }

  const violations = policyEngine.evaluate(result.desiredYaml);
  const denyViolations = violations.filter((v) => v.severity === "deny");
  if (denyViolations.length > 0) {
    const msgs = denyViolations
      .map((v) => `[${v.service}] ${v.rule}: ${v.message}`)
      .join("\n");
    return {
      isError: true,
      resultMessage: `Policy violation(s) detected. Remediation is blocked:\n${msgs}`,
    };
  }

  // Reuse the plan_ready / requestConfirm pattern (same as plan_stack)
  const confirm = await ctx.requestConfirm({
    composeYaml: result.desiredYaml,
    diff: result.diff,
  });
  if (confirm.kind !== "approve") {
    return { isError: false, resultMessage: "User declined remediation.", userDeclined: true };
  }

  // Re-apply desired state with rollback protection
  const r = yield* applyWithRollback(parsed.stackName, result.desiredYaml, undefined, [], ctx);

  // For `extra` status: report orphan services, mark not fully clean
  let resultMessage = r.resultMessage;
  let fullyClean = r.ok;
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
    details: { status: result.diff.status, ok: r.ok, fullyClean },
  });
  return { isError: !r.ok, resultMessage };
}

async function* requestSecretsAndPatch(
  service: string,
  keys: string[],
  ctx: LoopContext,
  currentInput: unknown,
): AsyncGenerator<LoopEvent, { patchedInput: unknown } | null> {
  const resp = await ctx.requestSecretsInput(service, keys, "missing required env");
  if (resp.kind !== "secrets_input_values") return null;
  const input = currentInput as {
    stackName: string;
    services: Record<string, { env_file?: string[]; environment?: Record<string, string> }>;
  };
  const path = await import("node:path");
  const fs = await import("node:fs/promises");
  const secretsDir = path.join(ctx.cwd, ".docker-agent", "secrets");
  await fs.mkdir(secretsDir, { recursive: true });
  const file = path.join(secretsDir, `${input.stackName}-${service}.env`);
  const lines = `${Object.entries(resp.values)
    .map(([k, v]) => `${k}=${v}`)
    .join("\n")}\n`;
  await fs.writeFile(file, lines, { mode: 0o600 });
  const rel = `./.docker-agent/secrets/${input.stackName}-${service}.env`;
  const svc = input.services[service];
  if (svc) {
    svc.env_file = svc.env_file ?? [];
    if (!svc.env_file.includes(rel)) svc.env_file.push(rel);
  }
  return { patchedInput: input };
}

async function* runDirectDestroyStack(
  stackName: string,
  removeVolumes: boolean,
  ctx: LoopContext,
): AsyncGenerator<LoopEvent, void> {
  const input = destroyStack.inputSchema.parse({
    stackName,
    ...(removeVolumes ? { removeVolumes: true } : {}),
  });
  if (removeVolumes) {
    const phrase = `DESTROY ${stackName}`;
    const typed = await ctx.requestTypedConfirm(
      phrase,
      `This will destroy the stack ${stackName} and delete all its volumes.`,
    );
    if (typed.kind !== "typed_confirm_value" || typed.value !== phrase) {
      yield { type: "assistant_text", delta: "destroy_stack aborted: typed confirmation did not match" };
      return;
    }
  } else if (!ctx.allowSet.has("destroy_stack")) {
    const resp = await ctx.requestPermission("destroy_stack", input);
    if (resp.kind === "deny") {
      yield { type: "assistant_text", delta: "destroy_stack aborted: permission denied" };
      return;
    }
    if (resp.kind === "always_allow_in_session") ctx.allowSet.add("destroy_stack");
  }
  yield* runTool(destroyStack, input, ctx);
}

export async function* query(params: QueryParams): AsyncGenerator<LoopEvent, void> {
  const { ctx, provider, model } = params;
  const userConfig = loadUserConfig();

  const rootPolicyPath = path.join(ctx.cwd, "project-policies.yaml");
  const legacyPolicyPath = path.join(ctx.cwd, ".docker-agent", "policies.yaml");
  const projectPolicyPath = fs.existsSync(rootPolicyPath) ? rootPolicyPath : legacyPolicyPath;

  const policyEngine = new PolicyEngine({
    userConfig,
    projectPolicyPath,
  });
  const messages = [...params.messages];
  const lastUser = [...messages]
    .reverse()
    .find((m): m is { role: "user"; content: string } => m.role === "user");

  if (lastUser && isDestroyAllPrompt(lastUser.content)) {
    const typed = await ctx.requestTypedConfirm(
      "DESTROY ALL",
      `This will destroy ${ctx.stateStore.list().length} stacks.`,
    );
    if (typed.kind !== "typed_confirm_value" || typed.value !== "DESTROY ALL") {
      yield {
        type: "assistant_text",
        delta: "destroy_all aborted: typed confirmation did not match",
      };
      return;
    }
    const parsed = destroyAllStacks.inputSchema.parse({});
    yield* runTool(destroyAllStacks, parsed, ctx);
    return;
  }

  const directDestroy = lastUser ? parseDirectDestroyStack(lastUser.content) : null;
  if (directDestroy) {
    yield* runDirectDestroyStack(directDestroy.stackName, directDestroy.removeVolumes, ctx);
    return;
  }

  const mode = lastUser ? classifyIntent(lastUser.content) : "react";
  const maxIterations = LOOP_LIMITS[mode];

  for (let iter = 0; iter < maxIterations; iter++) {
    if (ctx.abortSignal.aborted) return;
    yield { type: "iteration_start", n: iter + 1 };
    const stream = runProvider(provider, messages, mode, ctx, model);
    let collected: ProviderTurnResult = { text: "", toolUses: [], stopReason: "end_turn" };
    while (true) {
      if (ctx.abortSignal.aborted) return;
      const r = await stream.next();
      if (r.done) {
        collected = r.value;
        break;
      }
      yield r.value;
    }
    if (collected.stopReason === "max_tokens") {
      yield {
        type: "error",
        error: new Error("provider response stopped: max tokens reached"),
      };
      return;
    }
    messages.push({
      role: "assistant",
      content: assistantBlocksFromCollected(collected.text, collected.toolUses),
    });
    if (collected.toolUses.length === 0) return;

    for (const tu of collected.toolUses) {
      if (ctx.abortSignal.aborted) return;
      if (tu.name === "plan_stack") {
        const r = yield* handlePlanStackToolUse(tu, ctx, policyEngine);
        messages.push({
          role: "tool",
          toolUseId: tu.id,
          content: r.resultMessage,
          isError: r.isError,
        });
        if (r.userDeclined) return;
        continue;
      }
      if (tu.name === "destroy_all_stacks") {
        const typed = await ctx.requestTypedConfirm(
          "DESTROY ALL",
          `This will destroy ${ctx.stateStore.list().length} stacks.`,
        );
        if (typed.kind !== "typed_confirm_value" || typed.value !== "DESTROY ALL") {
          messages.push({
            role: "tool",
            toolUseId: tu.id,
            content: "destroy_all aborted: typed confirmation did not match",
            isError: false,
          });
          continue;
        }
        let parsed: unknown;
        try {
          parsed = destroyAllStacks.inputSchema.parse(JSON.parse(tu.argsPartial || "{}"));
        } catch (err) {
          messages.push({
            role: "tool",
            toolUseId: tu.id,
            content: `validation failed: ${(err as Error).message}`,
            isError: true,
          });
          continue;
        }
        const result = yield* runTool(destroyAllStacks, parsed as never, ctx);
        messages.push({
          role: "tool",
          toolUseId: tu.id,
          content: JSON.stringify(result),
          isError: false,
        });
        continue;
      }
      if (tu.name === "remediate_drift") {
        const r = yield* handleRemediateDriftToolUse(tu, ctx, policyEngine);
        messages.push({
          role: "tool",
          toolUseId: tu.id,
          content: r.resultMessage,
          isError: r.isError,
        });
        if (r.userDeclined) return;
        continue;
      }
      const tool = findToolByName(getToolsForMode(mode), tu.name);
      if (!tool) {
        messages.push({
          role: "tool",
          toolUseId: tu.id,
          content: `unknown tool: ${tu.name}`,
          isError: true,
        });
        continue;
      }
      let parsed: unknown = {};
      try {
        parsed = tool.inputSchema.parse(JSON.parse(tu.argsPartial || "{}"));
      } catch (err) {
        messages.push({
          role: "tool",
          toolUseId: tu.id,
          content: `validation failed: ${(err as Error).message}`,
          isError: true,
        });
        continue;
      }
      if (tool.name === "destroy_stack") {
        const stackName = (parsed as { stackName: string }).stackName;
        const removeVolumes = (parsed as { removeVolumes?: boolean }).removeVolumes;
        if (removeVolumes) {
          const phrase = `DESTROY ${stackName}`;
          const typed = await ctx.requestTypedConfirm(
            phrase,
            `This will destroy the stack ${stackName} and delete all its volumes.`,
          );
          if (typed.kind !== "typed_confirm_value" || typed.value !== phrase) {
            messages.push({
              role: "tool",
              toolUseId: tu.id,
              content: "destroy_stack aborted: typed confirmation did not match",
              isError: false,
            });
            continue;
          }
        } else if (!ctx.allowSet.has(tool.name)) {
          const resp = await ctx.requestPermission(tool.name, parsed);
          if (resp.kind === "deny") {
            messages.push({
              role: "tool",
              toolUseId: tu.id,
              content: "User denied permission.",
              isError: false,
            });
            continue;
          }
          if (resp.kind === "always_allow_in_session") ctx.allowSet.add(tool.name);
        }
      } else if (tool.needsPermission(parsed)) {
        if (!ctx.allowSet.has(tool.name)) {
          const resp = await ctx.requestPermission(tool.name, parsed);
          if (resp.kind === "deny") {
            messages.push({
              role: "tool",
              toolUseId: tu.id,
              content: "User denied permission.",
              isError: false,
            });
            continue;
          }
          if (resp.kind === "always_allow_in_session") ctx.allowSet.add(tool.name);
        }
      }
      const result = yield* runTool(tool as Tool, parsed, ctx);
      messages.push({
        role: "tool",
        toolUseId: tu.id,
        content: JSON.stringify(result),
        isError: false,
      });
    }

    if (ctx.logger) {
      const actions = collected.toolUses.map((tu) => tu.name);
      const observations = collected.toolUses.map((tu) => tu.name);
      ctx.logger.log({
        ts: new Date().toISOString(),
        level: "info",
        sessionId: ctx.sessionId ?? "unknown",
        iteration: iter + 1,
        category: "iteration_summary",
        message: `iteration ${iter + 1}: ${actions.length} action(s)`,
        data: {
          thoughtLength: collected.text.length,
          actions,
          observations,
          stopReason: collected.stopReason,
        },
      });
    }
  }
  yield {
    type: "error",
    error: new Error(`agent loop reached max iterations (${maxIterations})`),
  };
}
