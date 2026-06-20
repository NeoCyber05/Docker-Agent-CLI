import * as os from "node:os";
import * as path from "node:path";
import type { DraftServiceSpec } from "./specSchemas";

export const SENSITIVE_HOST_PATHS: readonly RegExp[] = [
  /^\/etc\b/,
  /^\/proc\b/,
  /^\/sys\b/,
  /^\/boot\b/,
  /^\/var\/run\/docker\.sock$/,
  /^\/dev\b/,
  /^\/root\b/,
];

export interface VolumeIssue {
  code: "path_traversal" | "sensitive_host_path";
  service: string;
  volume: string;
  message: string;
}

export function checkVolumeSafety(
  cwd: string,
  services: Record<string, DraftServiceSpec>,
): VolumeIssue[] {
  const issues: VolumeIssue[] = [];
  const home = os.homedir();

  for (const [svcName, spec] of Object.entries(services)) {
    for (const vol of spec.volumes ?? []) {
      const hostPart = vol.split(":")[0];
      if (hostPart === undefined) continue;

      const expanded = hostPart.startsWith("~/") ? path.join(home, hostPart.slice(2)) : hostPart;
      const resolved = path.isAbsolute(expanded) ? expanded : path.resolve(cwd, expanded);

      if (resolved.startsWith(path.join(home, ".ssh"))) {
        issues.push({
          code: "sensitive_host_path",
          service: svcName,
          volume: vol,
          message: `bind mount '${vol}' targets ~/.ssh — refusing to expose SSH keys to a container`,
        });
        continue;
      }

      for (const pattern of SENSITIVE_HOST_PATHS) {
        if (pattern.test(expanded)) {
          issues.push({
            code: "sensitive_host_path",
            service: svcName,
            volume: vol,
            message: `bind mount '${vol}' targets sensitive host path '${expanded}'`,
          });
          break;
        }
      }
      if (issues.length > 0 && issues[issues.length - 1]?.volume === vol) continue;

      if (!path.isAbsolute(expanded)) {
        const relativeToCwd = path.relative(cwd, resolved);
        if (relativeToCwd.startsWith("..")) {
          issues.push({
            code: "path_traversal",
            service: svcName,
            volume: vol,
            message: `bind mount '${vol}' resolves outside the project directory (${resolved})`,
          });
        }
      }
    }
  }

  return issues;
}
