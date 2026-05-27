import * as crypto from "node:crypto";
import type { EnvSnapshot } from "src/types/stack";

export const SECRET_KEY_PATTERN =
  /(?:^|[_-])(password|passwd|secret|token|api[_-]?key|credential|private[_-]?key|bearer|auth)\b(?:[_-]|$)/i;

export function shouldRedact(key: string): boolean {
  return SECRET_KEY_PATTERN.test(key);
}

export function hashSecret(value: string, salt: string): string {
  return crypto.createHmac("sha256", salt).update(value).digest("hex");
}

export function redactEnv(env: Record<string, string>, stackName: string): EnvSnapshot {
  const visible: Record<string, string> = {};
  const secretKeys: string[] = [];
  const secretHashesByKey: Record<string, string> = {};
  for (const [k, v] of Object.entries(env)) {
    if (shouldRedact(k)) {
      secretKeys.push(k);
      secretHashesByKey[k] = hashSecret(v, stackName);
    } else {
      visible[k] = v;
    }
  }
  return { visible, secretKeys, secretHashesByKey };
}

export function scrubLine(line: string, knownSecretKeys: Set<string>): string {
  let scrubbed = line;
  for (const key of knownSecretKeys) {
    const re = new RegExp(`${escapeRegExp(key)}=("[^"]*"|'[^']*'|[^\\s]+)`, "g");
    scrubbed = scrubbed.replace(re, `${key}=***`);
  }
  return scrubbed;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
