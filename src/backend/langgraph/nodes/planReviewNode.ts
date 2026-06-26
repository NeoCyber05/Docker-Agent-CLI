import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { LoopContext } from "src/loopContext";
import type { PolicyEngine } from "src/policy/PolicyEngine";
import { formatPlanBlocker } from "src/query";
import { scrubLine } from "src/state/secretRedactor";
import { type PlanStackInput, type PlanStackResult, planStack } from "src/tools/planStack";
import { collectSecretKeys } from "src/tools/shared/secretKeys";
import type { LoopEvent } from "src/types/events";
import type { Message } from "src/types/message";
import type { AgentState } from "../state";
import { runApplyWithRollback } from "./applyWithRollback";

export interface PlanReviewNodeDeps {
  ctx: LoopContext;
  policyEngine: PolicyEngine;
  emit: (ev: LoopEvent) => void;
}

async function requestSecretsAndPatch(
  service: string,
  keys: string[],
  ctx: LoopContext,
  currentInput: PlanStackInput,
): Promise<{ patchedInput: PlanStackInput } | null> {
  const resp = await ctx.requestSecretsInput(service, keys, "missing required env");
  if (resp.kind !== "secrets_input_values") return null;
  const input = currentInput as unknown as {
    stackName: string;
    services: Record<string, { env_file?: string[]; environment?: Record<string, string> }>;
  };
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
  return { patchedInput: input as unknown as PlanStackInput };
}

async function runPlanStack(
  input: PlanStackInput,
  ctx: LoopContext,
  emit: (ev: LoopEvent) => void,
): Promise<PlanStackResult> {
  emit({ type: "tool_call", name: planStack.name, input });
  const gen = planStack.call(input, ctx);
  let result: PlanStackResult;
  while (true) {
    const r = await gen.next();
    if (r.done) {
      result = r.value;
      break;
    }
    emit({ type: "tool_progress", msg: r.value.msg });
  }
  return result;
}

export const planReviewNode =
  ({ ctx, policyEngine, emit }: PlanReviewNodeDeps) =>
  async (state: typeof AgentState.State) => {
    const last = state.messages[state.messages.length - 1];
    if (!last || last.role !== "assistant") return {};

    const planCall = (
      last.content as Array<{ type: string; id?: string; name?: string; input?: unknown }>
    ).find((b) => b.type === "tool_use" && b.name === "plan_stack");
    if (!planCall || !planCall.id) return {};

    let parsedInput: PlanStackInput;
    try {
      parsedInput = planStack.inputSchema.parse(planCall.input);
    } catch (err) {
      const msg = `plan_stack validation failed: ${(err as Error).message}`;
      return {
        messages: [
          { role: "tool", toolUseId: planCall.id, content: msg, isError: true } satisfies Message,
        ],
      };
    }

    let planResult: Extract<PlanStackResult, { blocked: false }> | undefined;

    while (true) {
      const result = await runPlanStack(parsedInput, ctx, emit);

      if (result.blocked) {
        if (result.reason === "missing_config_file") {
          const paths = result.missingFiles.join(", ");
          const msg = `Missing content for bind-mounted config file(s): ${paths}. Re-run plan_stack including each path in the configFiles map with its full content.`;
          return {
            messages: [
              {
                role: "tool",
                toolUseId: planCall.id,
                content: msg,
                isError: true,
              } satisfies Message,
            ],
          };
        }
        if (
          result.reason === "invalid_spec" ||
          result.reason === "invalid_dependency" ||
          result.reason === "port_conflict" ||
          result.reason === "resource_limit" ||
          result.reason === "db_port_exposed" ||
          result.reason === "unsafe_volume" ||
          result.reason === "undeclared_network" ||
          result.reason === "invalid_yaml"
        ) {
          const msg = formatPlanBlocker(result);
          return {
            messages: [
              {
                role: "tool",
                toolUseId: planCall.id,
                content: msg,
                isError: true,
              } satisfies Message,
            ],
          };
        }
        const injected: Record<string, string[]> = result.missingByService;
        let patched: PlanStackInput | null = parsedInput;
        for (const [service, keys] of Object.entries(injected)) {
          const resp = await requestSecretsAndPatch(service, keys, ctx, patched ?? parsedInput);
          if (resp === null) {
            return {
              messages: [
                {
                  role: "tool",
                  toolUseId: planCall.id,
                  content: "User cancelled secrets input.",
                  isError: false,
                } satisfies Message,
              ],
            };
          }
          patched = resp.patchedInput;
        }
        if (patched) {
          parsedInput = patched;
        }
        continue;
      }

      // Valid plan — emit tool_result before moving to approval/apply.
      emit({ type: "tool_result", name: planStack.name, output: result });
      planResult = result;
      break;
    }

    // Redact secret-looking values from config-file content for display only;
    // runApplyWithRollback writes the real planResult.configFiles content.
    const secretKeys = collectSecretKeys(parsedInput.stackName, {
      cwd: ctx.cwd,
      stateStore: ctx.stateStore,
    });

    const violations = policyEngine.evaluate(planResult.composeYaml);
    const denyViolations = violations.filter((v) => v.severity === "deny");
    if (denyViolations.length > 0) {
      const msgs = denyViolations.map((v) => `[${v.service}] ${v.rule}: ${v.message}`).join("\n");
      const msg = `Policy violation(s) detected. Deployment is blocked:\n${msgs}`;
      return {
        messages: [
          { role: "tool", toolUseId: planCall.id, content: msg, isError: true } satisfies Message,
        ],
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
      return {
        messages: [
          {
            role: "tool",
            toolUseId: planCall.id,
            content: "plan denied by user",
            isError: false,
          } satisfies Message,
        ],
        aborted: true,
      };
    }

    const applyParams: {
      stackName: string;
      desiredYaml: string;
      configFiles: typeof planResult.configFiles;
      ctx: LoopContext;
      emit: (ev: LoopEvent) => void;
      scaleOverrides?: Record<string, number>;
    } = {
      stackName: parsedInput.stackName,
      desiredYaml: planResult.composeYaml,
      configFiles: planResult.configFiles,
      ctx,
      emit,
    };
    if (Object.keys(planResult.scaleOverrides).length) {
      applyParams.scaleOverrides = planResult.scaleOverrides;
    }
    const applyResult = await runApplyWithRollback(applyParams);

    return {
      messages: [
        {
          role: "tool",
          toolUseId: planCall.id,
          content: applyResult.resultMessage,
          isError: !applyResult.ok,
        } satisfies Message,
      ],
    };
  };
