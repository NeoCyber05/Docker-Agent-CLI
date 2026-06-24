import type { ServiceSpec, StackDefinition } from "src/types/stack";
import { parse as parseYaml, stringify as stringifyYaml } from "yaml";

export interface PlanInput {
  stackName: string;
  intent: string;
  services: Record<string, ServiceSpec>;
  networks?: Record<string, unknown>;
  volumes?: Record<string, unknown>;
}

export function buildStackDefinition(
  input: PlanInput,
  previous: StackDefinition | null,
  provider: string,
  generatedBy: string,
): { def: StackDefinition; scaleOverrides: Record<string, number> } {
  const now = new Date().toISOString();
  const scaleOverrides: Record<string, number> = {};

  for (const [name, spec] of Object.entries(input.services)) {
    if (spec.scale !== undefined && spec.scale > 1) {
      scaleOverrides[name] = spec.scale;
    }
  }

  return {
    def: {
      "x-docker-agent": {
        name: input.stackName,
        createdAt: previous?.["x-docker-agent"].createdAt ?? now,
        lastApplied: previous?.["x-docker-agent"].lastApplied ?? null,
        intent: input.intent,
        provider,
        generatedBy,
        envFileSources: previous?.["x-docker-agent"].envFileSources ?? {},
      },
      services: input.services,
      ...(input.networks ? { networks: input.networks } : {}),
      ...(input.volumes ? { volumes: input.volumes } : {}),
    },
    scaleOverrides,
  };
}

export function stackToYaml(def: StackDefinition): string {
  return stringifyYaml(def);
}

/** Strip internal x-docker-agent metadata for user-facing compose previews. */
export function composeYamlForPreview(composeYaml: string): string {
  try {
    const parsed = parseYaml(composeYaml);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return composeYaml;
    }
    const { "x-docker-agent": _meta, ...rest } = parsed as Record<string, unknown>;
    return stringifyYaml(rest).trimEnd();
  } catch {
    return composeYaml;
  }
}
