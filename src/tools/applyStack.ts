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
import { findInvalidFileBinds } from "./shared/configFiles";
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

export interface UnhealthyService {
  service: string;
  /** e.g. "exited", "created", "restarting", "health: starting", "not created" */
  status: string;
}

// Container states a long-running service won't recover from on its own. Seeing
// one means the apply has already failed — stop waiting out the deadline.
const TERMINAL_STATES = new Set(["exited", "dead"]);

/** Describe a service's unhealthy status, or null when it is healthy/running. */
function unhealthyStatus(row: ComposePsRow | undefined): string | null {
  if (!row) return "not created";
  if (row.Health) return row.Health === "healthy" ? null : `health: ${row.Health}`;
  return row.State === "running" ? null : row.State;
}

export async function verifyHealth(
  bound: BoundComposeRunner,
  expectedServices: string[],
  deadlineMs: number, // clamped 10_000..600_000
  abort: AbortSignal,
): Promise<{ healthy: boolean; unhealthy: UnhealthyService[] }> {
  const POLL_INTERVAL_MS = POLL_INTERVAL_MS_DEFAULT; // 2s
  const deadline = Date.now() + deadlineMs;
  while (true) {
    if (abort.aborted) {
      return {
        healthy: false,
        unhealthy: expectedServices.map((service) => ({ service, status: "aborted" })),
      };
    }
    let rows: ComposePsRow[] = [];
    try {
      rows = await bound.ps({ json: true });
    } catch {
      // treat as unhealthy, keep polling
    }
    const unhealthy: UnhealthyService[] = [];
    let crashed = false;
    for (const service of expectedServices) {
      const row = rows.find((r) => r.Service === service);
      const status = unhealthyStatus(row);
      if (status === null) continue;
      unhealthy.push({ service, status });
      if (row && TERMINAL_STATES.has(row.State.toLowerCase())) crashed = true;
    }
    if (unhealthy.length === 0) return { healthy: true, unhealthy: [] };
    // Fail-fast: a crashed container won't recover — don't wait out the deadline.
    if (crashed) return { healthy: false, unhealthy };
    if (Date.now() >= deadline) return { healthy: false, unhealthy };
    await new Promise<void>((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
}

const FAILURE_LOG_TAIL = 15;

/** Best-effort: tail recent logs of failed services to attach to the apply error. */
async function collectFailureLogs(
  bound: BoundComposeRunner,
  services: string[],
  secretKeys: Set<string>,
): Promise<string> {
  const sections: string[] = [];
  for (const svc of services) {
    let buf = "";
    try {
      const gen = bound.logs({ service: svc, tailLines: FAILURE_LOG_TAIL });
      while (true) {
        const r = await gen.next();
        if (r.done) break;
        buf += r.value;
      }
    } catch {
      // logs are diagnostic-only; ignore failures (e.g. a mocked runner)
    }
    const lines = buf.split("\n").filter((l) => l.trim());
    if (lines.length === 0) continue;
    const scrubbed = lines
      .slice(-FAILURE_LOG_TAIL)
      .map((l) => scrubLine(l, secretKeys).trimEnd())
      .join("\n");
    sections.push(`--- ${svc} ---\n${scrubbed}`);
  }
  return sections.join("\n\n");
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

    // Refuse before `compose up` if any file-like bind source is missing or is a
    // directory. Docker would otherwise silently auto-create an empty directory
    // at the source and then fail mounting it onto the image's file. Config
    // files authored by the agent are written before this tool runs, so a hit
    // here means the LLM emitted a file bind without providing its content (or a
    // stale Docker-created dir was left behind).
    const invalidBinds = findInvalidFileBinds(def.services, ctx.cwd);
    if (invalidBinds.length > 0) {
      return {
        ok: false,
        exitCode: 1,
        yamlPath,
        errorOutput:
          "Refusing to start: every file bind-mount source must be a real file before " +
          "'compose up' (Docker auto-creates a directory otherwise). Provide the file " +
          "content via configFiles, or create the files on disk:\n" +
          invalidBinds.map((b) => `  - ${b.path} (${b.service}): ${b.reason}`).join("\n"),
      };
    }

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
            const failedNames = healthResult.unhealthy.map((u) => u.service);
            const logs = await collectFailureLogs(bound, failedNames, secretKeys);
            return {
              ok: false,
              exitCode: 0,
              yamlPath,
              healthy: false,
              unhealthyServices: healthResult.unhealthy.map((u) => `${u.service} (${u.status})`),
              ...(logs ? { errorOutput: logs } : {}),
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
