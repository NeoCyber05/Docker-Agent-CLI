import type { DraftServiceSpec } from "./specSchemas";

export const MAX_SERVICES_PER_STACK = 25;
export const VALID_PORT_RANGE = { min: 1, max: 65535 } as const;
export const PRIVILEGED_PORT_THRESHOLD = 1024;

export interface ResourceLimitIssue {
  code: "too_many_services" | "invalid_port" | "privileged_port";
  path: string;
  message: string;
}

export function checkResourceLimits(
  services: Record<string, DraftServiceSpec>,
): ResourceLimitIssue[] {
  const issues: ResourceLimitIssue[] = [];

  const names = Object.keys(services);
  if (names.length > MAX_SERVICES_PER_STACK) {
    issues.push({
      code: "too_many_services",
      path: "services",
      message: `stack has ${names.length} services; maximum is ${MAX_SERVICES_PER_STACK}`,
    });
  }

  for (const [svcName, spec] of Object.entries(services)) {
    for (let i = 0; i < (spec.ports ?? []).length; i++) {
      const portValue = spec.ports?.[i];
      if (portValue === undefined) continue;
      const hostPort = extractHostPort(portValue);
      if (hostPort === null) continue;
      const path = `services.${svcName}.ports[${i}]`;
      if (hostPort < VALID_PORT_RANGE.min || hostPort > VALID_PORT_RANGE.max) {
        issues.push({
          code: "invalid_port",
          path,
          message: `host port ${hostPort} is outside valid range ${VALID_PORT_RANGE.min}-${VALID_PORT_RANGE.max}`,
        });
        continue;
      }
      if (hostPort < PRIVILEGED_PORT_THRESHOLD) {
        issues.push({
          code: "privileged_port",
          path,
          message: `host port ${hostPort} is privileged (< ${PRIVILEGED_PORT_THRESHOLD}); use a port >= ${PRIVILEGED_PORT_THRESHOLD}`,
        });
      }
    }
  }

  return issues;
}

function extractHostPort(value: string): number | null {
  const trimmed = value.trim();
  const slash = trimmed.lastIndexOf("/");
  const body = slash >= 0 ? trimmed.slice(0, slash) : trimmed;
  const parts = body.split(":");
  if (parts.length === 1) return null;
  const hostSegment = parts.length === 2 ? parts[0] : parts[parts.length - 2];
  if (hostSegment === undefined) return null;
  const match = hostSegment.match(/^(\d+)$/);
  if (!match) return null;
  return Number(match[1]);
}
