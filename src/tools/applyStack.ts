import * as fs from "node:fs";
import * as path from "node:path";
import type { Tool, ToolProgress } from "src/Tool";
import type { BoundComposeRunner, ComposePsRow } from "src/services/docker/composeRunner";
import { checkEnvFileGitStatus } from "src/services/docker/gitGuard";
import { parseStackDefinition } from "src/state/StateStore";
import { readEnvFile } from "src/state/envFile";
import { scrubLine, shouldRedact } from "src/state/secretRedactor";
import type { StackDefinition } from "src/types/stack";
import { parse as parseYaml } from "yaml";
import { z } from "zod";
import { validateImagesForTool } from "./shared/imageValidation";

export const ApplyStackInputSchema = z.object({
  stackName: z.string(),
  composeYaml: z.string(),
  scaleOverrides: z.record(z.number().int().min(1)).optional(),
});

export type ApplyStackInput = z.infer<typeof ApplyStackInputSchema>;

export interface ApplyStackResult {
  ok: boolean;
  exitCode: number;
  yamlPath: string;
  errorOutput?: string;
  healthy?: boolean; // false when health gate timed out
  unhealthyServices?: string[]; // services not running/healthy at deadline
}

const HEALTH_DEADLINE_MS_DEFAULT = 120_000; // 120s default
const POLL_INTERVAL_MS_DEFAULT = 2_000; // 2s default

function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n));
}

export async function verifyHealth(
  bound: BoundComposeRunner,
  expectedServices: string[],
  deadlineMs: number, // clamped 10_000..600_000
  abort: AbortSignal,
): Promise<{ healthy: boolean; unhealthy: string[] }> {
  const POLL_INTERVAL_MS = POLL_INTERVAL_MS_DEFAULT; // 2s
  const deadline = Date.now() + deadlineMs;
  while (true) {
    if (abort.aborted) return { healthy: false, unhealthy: expectedServices };
    let rows: ComposePsRow[] = [];
    try {
      rows = await bound.ps({ json: true });
    } catch {
      // treat as unhealthy, keep polling
    }
    const unhealthy = expectedServices.filter((svc) => {
      const row = rows.find((r) => r.Service === svc);
      if (!row) return true;
      if (row.Health) return row.Health !== "healthy";
      return row.State !== "running";
    });
    if (unhealthy.length === 0) return { healthy: true, unhealthy: [] };
    if (Date.now() >= deadline) return { healthy: false, unhealthy };
    await new Promise<void>((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
}

function resolveEnvFile(cwd: string, envFilePath: string): string {
  return path.isAbsolute(envFilePath) ? envFilePath : path.join(cwd, envFilePath);
}

function stackEnvFiles(def: StackDefinition): string[] {
  const envFiles = new Set<string>();
  for (const spec of Object.values(def.services)) {
    for (const envFile of spec.env_file ?? []) {
      envFiles.add(envFile);
    }
  }
  return [...envFiles];
}

function stackSecretKeys(def: StackDefinition, cwd: string): Set<string> {
  const keys = new Set<string>();
  for (const source of Object.values(def["x-docker-agent"].envFileSources)) {
    for (const key of source.addedKeys ?? []) {
      keys.add(key);
    }
  }
  for (const spec of Object.values(def.services)) {
    for (const key of Object.keys(spec.environment ?? {})) {
      if (shouldRedact(key)) keys.add(key);
    }
    for (const envFile of spec.env_file ?? []) {
      const values = readEnvFile(resolveEnvFile(cwd, envFile));
      for (const key of Object.keys(values)) {
        if (shouldRedact(key)) keys.add(key);
      }
    }
  }
  return keys;
}

export const applyStack: Tool<ApplyStackInput, ApplyStackResult> = {
  name: "apply_stack",
  description: "Apply a planned stack: write YAML, run Compose up via ComposeRunner.",
  inputSchema: ApplyStackInputSchema,
  category: "high-level",
  needsPermission: () => true,
  call: async function* (input, ctx): AsyncGenerator<ToolProgress, ApplyStackResult> {
    const yamlPath = path.join(ctx.cwd, ".docker-agent", "stacks", `${input.stackName}.yaml`);
    const def = parseStackDefinition(parseYaml(input.composeYaml), "apply_stack input");
    const imageValidation = await validateImagesForTool(
      Object.values(def.services).map((spec) => spec.image),
      ctx,
    );
    if (imageValidation.error) {
      return { ok: false, exitCode: 1, yamlPath, errorOutput: imageValidation.error };
    }
    for (const warning of imageValidation.warnings) {
      yield { type: "progress", msg: warning };
    }

    const envFiles = stackEnvFiles(def);
    const gitStatus = await checkEnvFileGitStatus(envFiles, ctx.cwd);
    if (gitStatus.refusals.length > 0) {
      return {
        ok: false,
        exitCode: 1,
        yamlPath,
        errorOutput: gitStatus.refusals
          .map((file) => `${file} is tracked by git. Run 'git rm --cached ${file}' first.`)
          .join("\n"),
      };
    }
    for (const file of gitStatus.warnings) {
      yield {
        type: "progress",
        msg: `warning: ${file} is neither tracked nor ignored. Add '.env*' to .gitignore to prevent accidental commit.`,
      };
    }

    const secretKeys = stackSecretKeys(def, ctx.cwd);

    yield { type: "progress", msg: `Writing stack YAML for ${input.stackName}...` };

    const stacksDir = path.join(ctx.cwd, ".docker-agent", "stacks");
    fs.mkdirSync(stacksDir, { recursive: true });
    ctx.stateStore.write(input.stackName, def);

    yield { type: "progress", msg: "Acquiring stack lock..." };
    const release = await ctx.stateStore.acquireLock(input.stackName, { timeoutMs: 30_000 });

    try {
      yield { type: "progress", msg: "Running Compose up -d..." };
      const bound = ctx.composeRunner.forStack(input.stackName, yamlPath);
      const gen = bound.up({
        detach: true,
        ...(input.scaleOverrides ? { scale: input.scaleOverrides } : {}),
      });

      let captured = "";
      while (true) {
        const r = await gen.next();
        if (r.done) {
          ctx.stateStore.appendHistory({
            ts: new Date().toISOString(),
            sessionId: "unknown",
            stackName: input.stackName,
            action: "apply",
            details: { exitCode: r.value },
          });

          if (r.value !== 0) {
            return { ok: false, exitCode: r.value, yamlPath, errorOutput: captured };
          }

          // Health gate: poll until all services are running/healthy or deadline elapses
          const expectedServices = Object.keys(def.services);
          const rawDeadline = ctx.healthCheckDeadlineMs ?? HEALTH_DEADLINE_MS_DEFAULT;
          // Only clamp if using the default (not a test override)
          const deadlineMs =
            ctx.healthCheckDeadlineMs !== undefined
              ? rawDeadline
              : clamp(rawDeadline, 10_000, 600_000);
          yield { type: "progress", msg: "Waiting for services to become healthy..." };
          const healthResult = await verifyHealth(
            bound,
            expectedServices,
            deadlineMs,
            ctx.abortSignal,
          );

          if (!healthResult.healthy) {
            return {
              ok: false,
              exitCode: 0,
              yamlPath,
              healthy: false,
              unhealthyServices: healthResult.unhealthy,
            };
          }

          ctx.stateStore.write(input.stackName, {
            ...def,
            "x-docker-agent": {
              ...def["x-docker-agent"],
              lastApplied: new Date().toISOString(),
            },
          });
          return { ok: true, exitCode: r.value, yamlPath, healthy: true, unhealthyServices: [] };
        }

        const scrubbed = scrubLine(r.value, secretKeys);
        captured += scrubbed;
        yield { type: "progress", msg: scrubbed.trimEnd() };
      }
    } finally {
      release();
    }
  },
};
