import * as path from "node:path";
import type { StateStore } from "src/state/StateStore";
import { readEnvFile } from "src/state/envFile";
import { shouldRedact } from "src/state/secretRedactor";

export interface SecretKeysContext {
  cwd: string;
  stateStore: StateStore;
}

function resolveEnvFile(cwd: string, envFilePath: string): string {
  return path.isAbsolute(envFilePath) ? envFilePath : path.join(cwd, envFilePath);
}

/**
 * Collect known secret env keys for a stack so logs/output can be scrubbed.
 * Mirrors applyStack.ts:stackSecretKeys but sources the definition from state.
 * Sources:
 *   (a) `x-docker-agent.envFileSources[*].addedKeys` (unconditional),
 *   (b) per-service `environment` keys that look secret (shouldRedact),
 *   (c) per-service `env_file` keys (resolved against cwd) that look secret.
 */
export function collectSecretKeys(stackName: string, ctx: SecretKeysContext): Set<string> {
  const keys = new Set<string>();
  const def = ctx.stateStore.read(stackName);
  if (!def) return keys;

  for (const source of Object.values(def["x-docker-agent"].envFileSources)) {
    for (const key of source.addedKeys ?? []) keys.add(key);
  }
  for (const spec of Object.values(def.services)) {
    for (const key of Object.keys(spec.environment ?? {})) {
      if (shouldRedact(key)) keys.add(key);
    }
    for (const envFile of spec.env_file ?? []) {
      const values = readEnvFile(resolveEnvFile(ctx.cwd, envFile));
      for (const key of Object.keys(values)) {
        if (shouldRedact(key)) keys.add(key);
      }
    }
  }
  return keys;
}
