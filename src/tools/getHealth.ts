import type { Tool, ToolProgress } from "src/Tool";
import type { ContainerStats, EngineClient } from "src/services/docker/engineClient";
import { z } from "zod";

export const CRASH_LOOP_THRESHOLD = 3;

const BYTES_PER_MB = 1024 * 1024;

export interface ComputedStats {
  cpuPercent: number | null;
  memUsedMb: number | null;
  memLimitMb: number | null;
  memPercent: number | null;
}

/** Pure CPU/mem math over a raw dockerode stats sample. No Docker access. */
export function computeStats(raw: ContainerStats): ComputedStats {
  return {
    cpuPercent: computeCpuPercent(raw),
    ...computeMem(raw),
  };
}

function computeCpuPercent(raw: ContainerStats): number | null {
  const pre = raw.precpu_stats;
  if (!pre) return null; // first/only sample — no delta possible
  const sysNow = raw.cpu_stats.system_cpu_usage;
  const sysPre = pre.system_cpu_usage;
  if (sysNow === undefined || sysPre === undefined) return null;
  const systemDelta = sysNow - sysPre;
  if (systemDelta <= 0) return null;
  const cpuDelta = raw.cpu_stats.cpu_usage.total_usage - pre.cpu_usage.total_usage;
  // `??` (not `||`): a daemon-reported `online_cpus: 0` is preserved rather than
  // falling back to percpu length. Modern daemons report a positive count or omit
  // the field, so the realistic input is null/undefined, which does fall through.
  const numCpus = raw.cpu_stats.online_cpus ?? raw.cpu_stats.cpu_usage.percpu_usage?.length ?? 1;
  return (cpuDelta / systemDelta) * numCpus * 100;
}

function computeMem(raw: ContainerStats): Omit<ComputedStats, "cpuPercent"> {
  const usage = raw.memory_stats.usage;
  const limit = raw.memory_stats.limit;
  if (usage === undefined || limit === undefined || limit === 0) {
    return { memUsedMb: null, memLimitMb: null, memPercent: null };
  }
  return {
    memUsedMb: usage / BYTES_PER_MB,
    memLimitMb: limit / BYTES_PER_MB,
    memPercent: (usage / limit) * 100,
  };
}

export const GetHealthInputSchema = z.object({
  stackName: z.string(),
});

export type GetHealthInput = z.infer<typeof GetHealthInputSchema>;

export interface HealthRow {
  name: string;
  service: string;
  status: string;
  health?: string;
  cpuPercent: number | null;
  memUsedMb: number | null;
  memLimitMb: number | null;
  memPercent: number | null;
  restartCount: number;
  crashLoop: boolean;
  error?: string;
}

export interface GetHealthResult {
  containers: HealthRow[];
  crashLoops: string[];
  error?: string;
}

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function isCrashLoop(restartCount: number, status: string): boolean {
  return restartCount >= CRASH_LOOP_THRESHOLD || status === "restarting";
}

export const getHealth: Tool<GetHealthInput, GetHealthResult> = {
  name: "get_health",
  description:
    "Per-container status, health, CPU%, memory, restart count, and crash-loop flag for a stack (read-only).",
  inputSchema: GetHealthInputSchema,
  category: "read-only",
  needsPermission: () => false,
  call: async function* (input, ctx): AsyncGenerator<ToolProgress, GetHealthResult> {
    yield { type: "progress", msg: `Inspecting health for ${input.stackName}...` };
    const engine = ctx.dockerEngine;

    let summaries: Awaited<ReturnType<EngineClient["listContainers"]>>;
    try {
      summaries = await engine.listContainers({
        all: true,
        filters: { label: [`com.docker.compose.project=${input.stackName}`] },
      });
    } catch (e) {
      return { containers: [], crashLoops: [], error: errMsg(e) };
    }

    const containers: HealthRow[] = [];
    for (const summary of summaries) {
      const name = summary.Names[0] ?? summary.Id;
      const service = summary.Labels["com.docker.compose.service"] ?? "";
      let status = summary.State;
      let health: string | undefined;
      let restartCount = 0;
      let cpuPercent: number | null = null;
      let memUsedMb: number | null = null;
      let memLimitMb: number | null = null;
      let memPercent: number | null = null;
      let error: string | undefined;

      // Independent best-effort step 1: inspect.
      try {
        const ins = await engine.inspect(summary.Id);
        status = ins.State.Status;
        health = ins.State.Health?.Status;
        restartCount = ins.RestartCount;
      } catch (e) {
        error = errMsg(e);
      }

      // Independent best-effort step 2: stats. Must NOT discard inspect data.
      try {
        const raw: ContainerStats = await engine.stats(summary.Id);
        const computed = computeStats(raw);
        cpuPercent = computed.cpuPercent;
        memUsedMb = computed.memUsedMb;
        memLimitMb = computed.memLimitMb;
        memPercent = computed.memPercent;
      } catch (e) {
        error = error ? `${error}; ${errMsg(e)}` : errMsg(e);
      }

      const crashLoop = isCrashLoop(restartCount, status);
      const row: HealthRow = {
        name,
        service,
        status,
        cpuPercent,
        memUsedMb,
        memLimitMb,
        memPercent,
        restartCount,
        crashLoop,
        ...(health !== undefined ? { health } : {}),
        ...(error !== undefined ? { error } : {}),
      };
      containers.push(row);
    }

    const crashLoops = containers.filter((r) => r.crashLoop).map((r) => r.name);
    return { containers, crashLoops };
  },
};
