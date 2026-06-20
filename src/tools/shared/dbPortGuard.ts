import type { DraftServiceSpec } from "./specSchemas";

interface DbPortEntry {
  imagePattern: RegExp;
  containerPorts: number[];
  label: string;
}

export const DB_PORT_MAP: DbPortEntry[] = [
  { imagePattern: /^postgres(:|$)/, containerPorts: [5432], label: "postgres" },
  { imagePattern: /^mysql(:|$)/, containerPorts: [3306], label: "mysql" },
  { imagePattern: /^mariadb(:|$)/, containerPorts: [3306], label: "mariadb" },
  { imagePattern: /^mongo(:|$)/, containerPorts: [27017], label: "mongo" },
  { imagePattern: /^redis(:|$)/, containerPorts: [6379], label: "redis" },
];

export interface DbPortExposureIssue {
  service: string;
  image: string;
  containerPort: number;
  hostPort: number;
  message: string;
}

export function checkDbPortExposure(
  services: Record<string, DraftServiceSpec>,
): DbPortExposureIssue[] {
  const issues: DbPortExposureIssue[] = [];
  for (const [svcName, spec] of Object.entries(services)) {
    const entry = DB_PORT_MAP.find((e) => e.imagePattern.test(spec.image));
    if (!entry) continue;
    for (const portValue of spec.ports ?? []) {
      const parsed = parseHostAndContainerPort(portValue);
      if (!parsed) continue;
      if (entry.containerPorts.includes(parsed.hostPort)) {
        issues.push({
          service: svcName,
          image: spec.image,
          containerPort: parsed.containerPort,
          hostPort: parsed.hostPort,
          message: `database ${entry.label} default port ${parsed.hostPort} is published to host port ${parsed.hostPort}; remove the port mapping or use a non-default container port — the service is reachable from other compose services without publishing`,
        });
      }
    }
  }
  return issues;
}

function parseHostAndContainerPort(
  value: string,
): { hostPort: number; containerPort: number } | null {
  const trimmed = value.trim();
  const slash = trimmed.lastIndexOf("/");
  const body = slash >= 0 ? trimmed.slice(0, slash) : trimmed;
  const parts = body.split(":");
  if (parts.length < 2) return null;
  const hostStr = parts.length === 2 ? parts[0] : parts[parts.length - 2];
  const containerStr = parts[parts.length - 1];
  if (hostStr === undefined || containerStr === undefined) return null;
  const hostMatch = hostStr.match(/^(\d+)$/);
  const containerMatch = containerStr.match(/^(\d+)$/);
  if (!hostMatch || !containerMatch) return null;
  return { hostPort: Number(hostMatch[1]), containerPort: Number(containerMatch[1]) };
}
