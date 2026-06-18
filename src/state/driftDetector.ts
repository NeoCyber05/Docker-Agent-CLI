import * as path from "node:path";
import type { ContainerInspect, EngineClient } from "src/services/docker/engineClient";
import type { ServiceDiff, ServiceSnapshot, ServiceSpec, StackDiff } from "src/types/stack";
import type { StateStore } from "./StateStore";
import { mergeEnv, readEnvFile } from "./envFile";
import { redactEnv } from "./secretRedactor";

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

/**
 * Parse ports from a container's NetworkSettings.Ports map into the short
 * Compose syntax "HOST:CONTAINER[/proto]" (e.g. "3406:3306", "8080:80/tcp").
 * Only entries that have at least one HostPort binding are included.
 */
function parseActualPorts(
  networkPorts: Record<string, Array<{ HostIp: string; HostPort: string }> | null>,
): string[] {
  const result: string[] = [];
  for (const [containerPortProto, bindings] of Object.entries(networkPorts)) {
    if (!bindings || bindings.length === 0) continue;
    // containerPortProto is e.g. "3306/tcp" or "80/tcp"
    const slashIdx = containerPortProto.indexOf("/");
    const containerPort =
      slashIdx >= 0 ? containerPortProto.slice(0, slashIdx) : containerPortProto;
    const proto = slashIdx >= 0 ? containerPortProto.slice(slashIdx + 1) : "tcp";
    for (const b of bindings) {
      if (!b.HostPort) continue;
      // Omit /tcp suffix (most common) to match Compose YAML convention
      const portStr =
        proto === "tcp"
          ? `${b.HostPort}:${containerPort}`
          : `${b.HostPort}:${containerPort}/${proto}`;
      result.push(portStr);
    }
  }
  // Sort for stable comparison
  return result.sort();
}

/**
 * Normalize a volume binding for comparison.
 * Docker Compose prefixes named volumes with "<stackName>_" and always appends
 * ":rw" or ":ro" to the actual mount. Strip both so we compare apples-to-apples
 * against the user's declared spec (e.g. "db_data:/var/lib/mysql").
 */
function normalizeVolume(vol: string, stackName: string): string {
  const parts = vol.split(":");
  if (parts.length < 2) return vol;
  let source = parts[0] as string;
  const target = parts[1] as string;
  // Strip mode suffix (:rw / :ro) added by Docker
  const rest = parts.slice(2).filter((p) => p !== "rw" && p !== "ro");
  // Strip stack-name prefix added by Compose for named volumes (not bind mounts)
  const prefix = `${stackName}_`;
  if (source.startsWith(prefix)) source = source.slice(prefix.length);
  return rest.length > 0 ? `${source}:${target}:${rest.join(":")}` : `${source}:${target}`;
}

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
  declaredEnvKeys: Set<string>,
): Array<{ field: string; from: unknown; to: unknown }> {
  const changes: Array<{ field: string; from: unknown; to: unknown }> = [];

  // image + replicaCount: always compare
  for (const f of ["image", "replicaCount"] as const) {
    if (JSON.stringify(desired[f]) !== JSON.stringify(actual[f])) {
      changes.push({ field: f, from: desired[f], to: actual[f] });
    }
  }

  // command: only diff when the user explicitly set one in the spec.
  // If desired.command is null the image's own entrypoint/CMD is authoritative.
  if (desired.command !== null) {
    if (JSON.stringify(desired.command) !== JSON.stringify(actual.command)) {
      changes.push({ field: "command", from: desired.command, to: actual.command });
    }
  }

  // ports: compare sorted lists
  const dp = [...desired.ports].sort();
  const ap = [...actual.ports].sort();
  if (JSON.stringify(dp) !== JSON.stringify(ap)) {
    changes.push({ field: "ports", from: dp, to: ap });
  }

  // volumes: compare sorted, normalized lists
  const dv = [...desired.volumes].sort();
  const av = [...actual.volumes].sort();
  if (JSON.stringify(dv) !== JSON.stringify(av)) {
    changes.push({ field: "volumes", from: dv, to: av });
  }

  // env: only compare keys the user explicitly declared (visible)
  for (const k of declaredEnvKeys) {
    if (desired.env.secretKeys.includes(k) || actual.env.secretKeys.includes(k)) continue;
    const a = desired.env.visible[k];
    const b = actual.env.visible[k];
    if (a !== b) changes.push({ field: `env.${k}`, from: a, to: b });
  }
  // env: secret keys by presence + hash mismatch (values redacted) — only declared keys
  for (const k of desired.env.secretKeys) {
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
    let serviceContainers = byService.get(svc);
    if (serviceContainers === undefined) {
      serviceContainers = [];
      byService.set(svc, serviceContainers);
    }
    serviceContainers.push(c);
  }
  const desiredServices = new Set(Object.keys(def.services));
  const actualServices = new Set(byService.keys());

  const serviceDiffs: ServiceDiff[] = [];
  for (const svc of new Set([...desiredServices, ...actualServices])) {
    const spec = def.services[svc];
    const containers = byService.get(svc) ?? [];

    // Collect the env keys the user explicitly declared so we only diff those.
    const declaredEnvMap = spec ? desiredEnv(spec, cwd) : {};
    const declaredEnvKeys = new Set(Object.keys(declaredEnvMap));

    const desiredSnap = spec
      ? snapshot(
          spec.image,
          spec.command ?? null,
          [...(spec.ports ?? [])].sort(),
          declaredEnvMap,
          [...(spec.volumes ?? [])].sort(),
          spec.scale ?? 1,
          stackName,
        )
      : null;

    let actualSnap: ServiceSnapshot | null = null;
    const first = containers[0];
    if (first !== undefined) {
      const mergedEnvMap = envArrayToMap(first.Config.Env ?? []);
      const actualPorts = parseActualPorts(first.NetworkSettings.Ports);
      const actualVolumes = (first.HostConfig.Binds ?? [])
        .map((v) => normalizeVolume(v, stackName))
        .sort();
      actualSnap = snapshot(
        first.Config.Image,
        first.Config.Cmd,
        actualPorts,
        mergedEnvMap,
        actualVolumes,
        containers.length,
        stackName,
        first.State.Status,
      );
    }

    const changes =
      desiredSnap && actualSnap
        ? diffSnapshots(desiredSnap, actualSnap, declaredEnvKeys)
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
