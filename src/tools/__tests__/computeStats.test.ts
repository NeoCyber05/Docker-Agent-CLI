import type { ContainerStats } from "src/services/docker/engineClient";
import { computeStats } from "src/tools/getHealth";
import { describe, expect, test } from "vitest";

const MB = 1024 * 1024;

describe("computeStats", () => {
  test("computes cpu and mem from a valid sample", () => {
    const raw = {
      cpu_stats: {
        cpu_usage: { total_usage: 200, percpu_usage: [1, 2] },
        system_cpu_usage: 2000,
        online_cpus: 2,
      },
      precpu_stats: { cpu_usage: { total_usage: 100 }, system_cpu_usage: 1000 },
      memory_stats: { usage: 50 * MB, limit: 100 * MB },
    } as unknown as ContainerStats;

    const result = computeStats(raw);
    // cpuDelta=100, systemDelta=1000, numCpus=2 -> (100/1000)*2*100 = 20
    expect(result.cpuPercent).toBeCloseTo(20);
    expect(result.memUsedMb).toBeCloseTo(50);
    expect(result.memLimitMb).toBeCloseTo(100);
    expect(result.memPercent).toBeCloseTo(50);
  });

  test("numCpus falls back to percpu_usage length then 1", () => {
    const raw = {
      cpu_stats: {
        cpu_usage: { total_usage: 300, percpu_usage: [1, 2, 3, 4] },
        system_cpu_usage: 2000,
      },
      precpu_stats: { cpu_usage: { total_usage: 100 }, system_cpu_usage: 1000 },
      memory_stats: {},
    } as unknown as ContainerStats;

    // cpuDelta=200, systemDelta=1000, numCpus=4 -> (200/1000)*4*100 = 80
    expect(computeStats(raw).cpuPercent).toBeCloseTo(80);
  });

  test("null cpuPercent when precpu_stats is absent (first sample)", () => {
    const raw = {
      cpu_stats: { cpu_usage: { total_usage: 200 }, system_cpu_usage: 2000, online_cpus: 1 },
      memory_stats: { usage: MB, limit: 2 * MB },
    } as unknown as ContainerStats;

    expect(computeStats(raw).cpuPercent).toBeNull();
  });

  test("null cpuPercent when system_cpu_usage missing on either side", () => {
    const raw = {
      cpu_stats: { cpu_usage: { total_usage: 200 }, online_cpus: 1 },
      precpu_stats: { cpu_usage: { total_usage: 100 }, system_cpu_usage: 1000 },
      memory_stats: {},
    } as unknown as ContainerStats;

    expect(computeStats(raw).cpuPercent).toBeNull();
  });

  test("null cpuPercent when systemDelta <= 0", () => {
    const raw = {
      cpu_stats: { cpu_usage: { total_usage: 200 }, system_cpu_usage: 1000, online_cpus: 1 },
      precpu_stats: { cpu_usage: { total_usage: 100 }, system_cpu_usage: 1000 },
      memory_stats: {},
    } as unknown as ContainerStats;

    expect(computeStats(raw).cpuPercent).toBeNull();
  });

  test("mem fields null when usage or limit missing", () => {
    const raw = {
      cpu_stats: { cpu_usage: { total_usage: 200 }, system_cpu_usage: 2000, online_cpus: 1 },
      precpu_stats: { cpu_usage: { total_usage: 100 }, system_cpu_usage: 1000 },
      memory_stats: { usage: MB },
    } as unknown as ContainerStats;

    const result = computeStats(raw);
    expect(result.memUsedMb).toBeNull();
    expect(result.memLimitMb).toBeNull();
    expect(result.memPercent).toBeNull();
  });
});
