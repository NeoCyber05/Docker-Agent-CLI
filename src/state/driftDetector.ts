import type { ContainerInspect, EngineClient } from "src/services/docker/engineClient";
import type { ServiceSnapshot, ServiceDiff, StackDiff, ServiceSpec } from "src/types/stack";
import type { StateStore } from "./StateStore";
import { readEnvFile, mergeEnv } from "./envFile";
import { redactEnv } from "./secretRedactor";
import * as path from "node:path";

const RUNTIME_ALLOWLIST = new Set([
  "PATH",
  "HOME",
  "HOSTNAME",
  "TERM",
  "LANG",
  "LC_ALL",
  "PWD",
  "SHLVL",
  "_",
]);

function envArrayToMap(env: string[]): Record<string, string> {
  const m: Record<string, string> = {};
  for (const line of env) {
    const i = line.indexOf("=");
    if (i < 0) continue;
    const k = line.slice(0, i);
    if (RUNTIME_ALLOWLIST.has(k)) continue;
    m[k] = line.slice(i + 1);
  }
  return m;
}

function desiredEnv(spec: ServiceSpec, cwd: string): Record<string, string> {
  const fromFile: Record<string, string> = {};
  for (const f of spec.env_file ?? []) {
    Object.assign(fromFile, readEnvFile(path.isAbsolute(f) ? f : path.join(cwd, f)));
  }
  return mergeEnv(fromFile, spec.environment ?? {});
}

function snapshot(
  image: string,
  cmd: string | string[] | null,
  ports: string[],
  envMap: Record<string, string>,
  volumes: string[],
  replicaCount: number,
  stackName: string,
  state?: string,
): ServiceSnapshot {
  return {
    image,
    command: cmd,
    ports,
    env: redactEnv(envMap, stackName),
    volumes,
    replicaCount,
    ...(state !== undefined ? { state } : {}),
  };
}

function diffSnapshots(
  desired: ServiceSnapshot,
  actual: ServiceSnapshot,
): Array<{ field: string; from: unknown; to: unknown }> {
  const changes: Array<{ field: string; from: unknown; to: unknown }> = [];
  const scalarFields: Array<keyof ServiceSnapshot> = [
    "image",
    "command",
    "replicaCount",
  ];
  for (const f of scalarFields) {
    if (JSON.stringify(desired[f]) !== JSON.stringify(actual[f])) {
      changes.push({ field: f as string, from: desired[f], to: actual[f] });
    }
  }
  if (JSON.stringify(desired.ports) !== JSON.stringify(actual.ports)) {
    changes.push({ field: "ports", from: desired.ports, to: actual.ports });
  }
  if (JSON.stringify(desired.volumes) !== JSON.stringify(actual.volumes)) {
    changes.push({ field: "volumes", from: desired.volumes, to: actual.volumes });
  }
  // env: visible diff by value
  const allVisibleKeys = new Set([
    ...Object.keys(desired.env.visible),
    ...Object.keys(actual.env.visible),
  ]);
  for (const k of allVisibleKeys) {
    const a = desired.env.visible[k];
    const b = actual.env.visible[k];
    if (a !== b) changes.push({ field: `env.${k}`, from: a, to: b });
  }
  // env: secret keys by presence + hash mismatch (values redacted)
  const allSecretKeys = new Set([...desired.env.secretKeys, ...actual.env.secretKeys]);
  for (const k of allSecretKeys) {
    const dh = desired.env.secretHashesByKey[k];
    const ah = actual.env.secretHashesByKey[k];
    if (dh !== ah) changes.push({ field: `env.${k}`, from: "***", to: "***" });
  }
  return changes;
}

export async function detectDrift(
  stackName: string,
  store: StateStore,
  engine: EngineClient,
  cwd: string = process.cwd(),
): Promise<StackDiff> {
  const def = store.read(stackName);
  if (!def) {
    return { stackName, status: "missing", serviceDiffs: [] };
  }
  const summaries = await engine.listContainers({
    all: true,
    filters: { label: [`com.docker.compose.project=${stackName}`] },
  });
  const inspects: ContainerInspect[] = await Promise.all(
    summaries.map((s) => engine.inspect(s.Id)),
  );
  const byService = new Map<string, ContainerInspect[]>();
  for (const c of inspects) {
    const svc = c.Config.Labels["com.docker.compose.service"];
    if (!svc) continue;
    if (!byService.has(svc)) byService.set(svc, []);
    byService.get(svc)!.push(c);
  }
  const desiredServices = new Set(Object.keys(def.services));
  const actualServices = new Set(byService.keys());

  const serviceDiffs: ServiceDiff[] = [];
  for (const svc of new Set([...desiredServices, ...actualServices])) {
    const spec = def.services[svc];
    const containers = byService.get(svc) ?? [];

    const desiredSnap = spec
      ? snapshot(
          spec.image,
          spec.command ?? null,
          spec.ports ?? [],
          desiredEnv(spec, cwd),
          spec.volumes ?? [],
          spec.scale ?? 1,
          stackName,
        )
      : null;

    let actualSnap: ServiceSnapshot | null = null;
    if (containers.length > 0) {
      const first = containers[0]!;
      const mergedEnvMap = envArrayToMap(first.Config.Env ?? []);
      actualSnap = snapshot(
        first.Config.Image,
        first.Config.Cmd,
        [],
        mergedEnvMap,
        first.HostConfig.Binds ?? [],
        containers.length,
        stackName,
        first.State.Status,
      );
    }

    const changes =
      desiredSnap && actualSnap
        ? diffSnapshots(desiredSnap, actualSnap)
        : desiredSnap
          ? [{ field: "service", from: "desired", to: "missing" }]
          : [{ field: "service", from: "missing", to: "extra" }];

    serviceDiffs.push({ service: svc, desired: desiredSnap, actual: actualSnap, changes });
  }

  const allInSync = serviceDiffs.every((d) => d.changes.length === 0);
  const allDesiredMissing = serviceDiffs.every((d) => d.desired && !d.actual);
  const anyExtra = serviceDiffs.some((d) => !d.desired && d.actual);

  let status: StackDiff["status"];
  if (allInSync) status = "in_sync";
  else if (allDesiredMissing) status = "missing";
  else if (anyExtra) status = "extra";
  else status = "drift";

  return { stackName, status, serviceDiffs };
}