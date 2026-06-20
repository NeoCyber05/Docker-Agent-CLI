import type { StateStore } from "src/state/StateStore";
import { shouldRedact } from "src/state/secretRedactor";
import { collectSecretKeys } from "src/tools/shared/secretKeys";
import type { StackDefinition, StackSummary } from "src/types/stack";
import { stringify as stringifyYaml } from "yaml";

export interface SlashDispatchContext {
  cwd: string;
  stateStore: StateStore;
}

export type DirectSlashResult = { ok: true; text: string } | { ok: false; error: string };

export function formatStacksTable(stacks: StackSummary[]): string {
  if (stacks.length === 0) {
    return "**Managed stacks**\n\nNo stacks defined under `.docker-agent/stacks/`.";
  }
  const header = "| Name | Services | Last applied |";
  const sep = "| --- | --- | --- |";
  const rows = stacks.map((s) => `| ${s.name} | ${s.serviceCount} | ${s.lastApplied ?? "never"} |`);
  return ["**Managed stacks**", "", header, sep, ...rows].join("\n");
}

function redactStackForDisplay(def: StackDefinition): StackDefinition {
  const clone = structuredClone(def);
  for (const spec of Object.values(clone.services)) {
    if (!spec.environment) continue;
    for (const [key, value] of Object.entries(spec.environment)) {
      if (shouldRedact(key)) spec.environment[key] = "***";
    }
  }
  return clone;
}

export function dispatchStacks(ctx: SlashDispatchContext): string {
  return formatStacksTable(ctx.stateStore.list());
}

export function dispatchYaml(stackName: string, ctx: SlashDispatchContext): DirectSlashResult {
  const def = ctx.stateStore.read(stackName);
  if (!def) {
    return { ok: false, error: `stack ${stackName} not found` };
  }
  const yaml = stringifyYaml(redactStackForDisplay(def));
  return { ok: true, text: `\`\`\`yaml\n${yaml.trimEnd()}\n\`\`\`` };
}

export function destroyStackPrompt(stackName: string, removeVolumes = false): string {
  return `Destroy stack ${stackName}${removeVolumes ? " with volumes" : ""}`;
}

export function isDestroyAllPrompt(content: string): boolean {
  return content.trim().toLowerCase() === "destroy all stacks";
}

export function parseDirectDestroyStack(
  content: string,
): { stackName: string; removeVolumes: boolean } | null {
  const trimmed = content.trim();
  const patterns = [
    /^Destroy stack (\S+)(?:\s+with volumes)?$/i,
    /^destroy (\S+)(?:\s+with volumes)?$/i,
  ];
  for (const pattern of patterns) {
    const match = trimmed.match(pattern);
    if (!match?.[1] || match[1].toLowerCase() === "all") continue;
    return {
      stackName: match[1],
      removeVolumes: /\swith volumes$/i.test(trimmed),
    };
  }
  return null;
}

export function dispatchSecretsList(
  stackName: string,
  ctx: SlashDispatchContext,
): DirectSlashResult {
  const def = ctx.stateStore.read(stackName);
  if (!def) {
    return { ok: false, error: `stack ${stackName} not found` };
  }
  const keys = [...collectSecretKeys(stackName, ctx)].sort();
  if (keys.length === 0) {
    return { ok: true, text: `No secret keys tracked for stack **${stackName}**.` };
  }
  const lines = keys.map((key) => `- ${key}`);
  return { ok: true, text: [`Secret keys for **${stackName}**:`, ...lines].join("\n") };
}
