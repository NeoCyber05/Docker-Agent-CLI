import type { ContainerStats } from "src/services/docker/engineClient";

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
  const numCpus = raw.cpu_stats.online_cpus ?? raw.cpu_stats.cpu_usage.percpu_usage?.length ?? 1;
  return (cpuDelta / systemDelta) * numCpus * 100;
}

function computeMem(raw: ContainerStats): {
  memUsedMb: number | null;
  memLimitMb: number | null;
  memPercent: number | null;
} {
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
