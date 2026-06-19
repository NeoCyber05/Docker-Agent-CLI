import type { Tool, ToolContext, ToolProgress } from "src/Tool";
import { z } from "zod";
import { ServicesSchema } from "./shared/specSchemas";

export interface PublishedPort {
  hostIp: string;
  hostPort: number;
  containerPort: number;
  protocol: "tcp" | "udp";
}

export interface PortConflict {
  source: "draft" | "running";
  service: string;
  hostIp: string;
  hostPort: number;
  protocol: "tcp" | "udp";
  conflictsWith: string;
}

export interface CheckPortConflictResult {
  ok: boolean;
  conflicts: PortConflict[];
  invalid: Array<{ service: string; value: string; message: string }>;
}

export const CheckPortConflictInputSchema = z.object({
  stackName: z.string().optional(),
  services: ServicesSchema,
});
export type CheckPortConflictInput = z.infer<typeof CheckPortConflictInputSchema>;

function parseProtocol(value: string): { body: string; protocol: "tcp" | "udp" } {
  const slash = value.lastIndexOf("/");
  if (slash >= 0) {
    const proto = value.slice(slash + 1).toLowerCase();
    if (proto === "tcp" || proto === "udp") {
      return { body: value.slice(0, slash), protocol: proto };
    }
  }
  return { body: value, protocol: "tcp" };
}

function expandRange(segment: string): number[] | null {
  const range = segment.match(/^(\d+)-(\d+)$/);
  if (!range) return null;
  const start = Number(range[1]);
  const end = Number(range[2]);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start > end) return null;
  const values: number[] = [];
  for (let port = start; port <= end; port++) values.push(port);
  return values;
}

function parsePortSegment(segment: string): number[] | { error: string } {
  const range = expandRange(segment);
  if (range) return range;
  if (/^\d+$/.test(segment)) return [Number(segment)];
  return { error: `invalid port segment "${segment}"` };
}

export function parsePublishedPorts(value: string): PublishedPort[] {
  const { body, protocol } = parseProtocol(value.trim());
  const parts = body.split(":");

  if (parts.length === 1) {
    const only = parts[0] as string;
    if (/^\d+$/.test(only)) return [];
    return [];
  }

  let hostIp = "0.0.0.0";
  let hostSegment: string;
  let containerSegment: string;

  if (parts.length === 2) {
    hostSegment = parts[0] as string;
    containerSegment = parts[1] as string;
  } else {
    containerSegment = parts[parts.length - 1] as string;
    hostSegment = parts[parts.length - 2] as string;
    const ipParts = parts.slice(0, -2);
    hostIp = ipParts.join(":").replace(/^\[|\]$/g, "");
  }

  const hostPorts = parsePortSegment(hostSegment);
  const containerPorts = parsePortSegment(containerSegment);
  if ("error" in hostPorts) return [];
  if ("error" in containerPorts) return [];

  if (hostPorts.length !== containerPorts.length) return [];

  return hostPorts.map((hostPort, index) => ({
    hostIp: hostIp || "0.0.0.0",
    hostPort,
    containerPort: containerPorts[index] as number,
    protocol,
  }));
}

function normalizeHostIp(hostIp: string): string {
  const trimmed = hostIp.trim();
  if (!trimmed || trimmed === "0.0.0.0" || trimmed === "::") return "0.0.0.0";
  return trimmed;
}

function bindingsConflict(a: PublishedPort, b: PublishedPort): boolean {
  if (a.protocol !== b.protocol || a.hostPort !== b.hostPort) return false;
  const aIp = normalizeHostIp(a.hostIp);
  const bIp = normalizeHostIp(b.hostIp);
  return aIp === "0.0.0.0" || bIp === "0.0.0.0" || aIp === bIp;
}

function bindingKey(binding: PublishedPort): string {
  return `${binding.protocol}:${normalizeHostIp(binding.hostIp)}:${binding.hostPort}`;
}

export async function checkPortConflicts(
  input: CheckPortConflictInput,
  ctx: ToolContext,
): Promise<CheckPortConflictResult> {
  const conflicts: PortConflict[] = [];
  const invalid: CheckPortConflictResult["invalid"] = [];
  const draftBindings: Array<{ service: string; binding: PublishedPort }> = [];

  for (const [service, spec] of Object.entries(input.services)) {
    for (const portValue of spec.ports ?? []) {
      const parsed = parsePublishedPorts(portValue);
      if (parsed.length === 0 && portValue.includes(":")) {
        const { body } = parseProtocol(portValue.trim());
        const parts = body.split(":");
        if (parts.length >= 2) {
          const hostSegment = (parts.length === 2 ? parts[0] : parts[parts.length - 2]) as string;
          const containerSegment = parts[parts.length - 1] as string;
          const hostPorts = parsePortSegment(hostSegment);
          const containerPorts = parsePortSegment(containerSegment);
          if (
            ("error" in hostPorts ||
              "error" in containerPorts ||
              (!("error" in hostPorts) &&
                !("error" in containerPorts) &&
                hostPorts.length !== containerPorts.length)) &&
            !/^\d+$/.test(portValue.trim())
          ) {
            invalid.push({
              service,
              value: portValue,
              message: "host and container port ranges must have equal length",
            });
            continue;
          }
        }
      }
      for (const binding of parsed) {
        draftBindings.push({ service, binding });
      }
    }
  }

  for (let i = 0; i < draftBindings.length; i++) {
    for (let j = i + 1; j < draftBindings.length; j++) {
      const left = draftBindings[i];
      const right = draftBindings[j];
      if (!left || !right) continue;
      if (bindingsConflict(left.binding, right.binding)) {
        conflicts.push({
          source: "draft",
          service: left.service,
          hostIp: left.binding.hostIp,
          hostPort: left.binding.hostPort,
          protocol: left.binding.protocol,
          conflictsWith: right.service,
        });
      }
    }
  }

  const containers = await ctx.dockerEngine.listContainers({ all: true });
  const runningBindings: Array<{ container: string; binding: PublishedPort }> = [];

  for (const summary of containers) {
    if (summary.State === "exited" || summary.State === "dead") continue;
    if (input.stackName && summary.Labels?.["com.docker.compose.project"] === input.stackName) {
      continue;
    }
    const inspected = (await ctx.dockerEngine.inspect(summary.Id)) as {
      NetworkSettings?: {
        Ports?: Record<string, Array<{ HostIp?: string; HostPort?: string }> | null>;
      };
    };
    const ports = inspected.NetworkSettings?.Ports ?? {};
    for (const [containerPortKey, bindings] of Object.entries(ports)) {
      if (!bindings) continue;
      const [containerPortRaw, protocolRaw] = containerPortKey.split("/");
      const protocol = protocolRaw === "udp" ? "udp" : "tcp";
      const containerPort = Number(containerPortRaw);
      for (const binding of bindings) {
        if (!binding.HostPort) continue;
        runningBindings.push({
          container: summary.Names?.[0] ?? summary.Id,
          binding: {
            hostIp: binding.HostIp ?? "0.0.0.0",
            hostPort: Number(binding.HostPort),
            containerPort,
            protocol,
          },
        });
      }
    }
  }

  for (const draft of draftBindings) {
    for (const running of runningBindings) {
      if (bindingsConflict(draft.binding, running.binding)) {
        conflicts.push({
          source: "running",
          service: draft.service,
          hostIp: draft.binding.hostIp,
          hostPort: draft.binding.hostPort,
          protocol: draft.binding.protocol,
          conflictsWith: running.container,
        });
      }
    }
  }

  conflicts.sort((a, b) => {
    const byService = a.service.localeCompare(b.service);
    if (byService !== 0) return byService;
    const byPort = a.hostPort - b.hostPort;
    if (byPort !== 0) return byPort;
    const byProtocol = a.protocol.localeCompare(b.protocol);
    if (byProtocol !== 0) return byProtocol;
    return a.source.localeCompare(b.source);
  });

  return { ok: conflicts.length === 0 && invalid.length === 0, conflicts, invalid };
}

export const checkPortConflict: Tool<CheckPortConflictInput, CheckPortConflictResult> = {
  name: "check_port_conflict",
  description:
    "Check draft published ports for internal conflicts and collisions with running Docker containers.",
  inputSchema: CheckPortConflictInputSchema,
  category: "read-only",
  needsPermission: () => false,
  call: async function* (input, ctx): AsyncGenerator<ToolProgress, CheckPortConflictResult> {
    yield { type: "progress", msg: "Checking published ports..." };
    return checkPortConflicts(input, ctx);
  },
};
