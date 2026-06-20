import type { DraftServiceSpec } from "./specSchemas";

export interface NetworkIssue {
  code: "undeclared_network";
  service: string;
  network: string;
  message: string;
}

export function checkNetworkReferences(
  services: Record<string, DraftServiceSpec>,
  networks?: Record<string, unknown>,
): NetworkIssue[] {
  const declared = new Set(Object.keys(networks ?? {}));
  const issues: NetworkIssue[] = [];

  for (const [svcName, spec] of Object.entries(services)) {
    for (const net of spec.networks ?? []) {
      if (!declared.has(net)) {
        issues.push({
          code: "undeclared_network",
          service: svcName,
          network: net,
          message: `service '${svcName}' references network '${net}' which is not declared in top-level networks`,
        });
      }
    }
  }

  return issues;
}
