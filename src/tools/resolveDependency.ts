import type { Tool, ToolProgress } from "src/Tool";
import { z } from "zod";
import { type DraftServiceSpec, ServicesSchema, type StackDraft } from "./shared/specSchemas";
import { prepareStackDraft } from "./shared/translator";

export const ResolveDependencyInputSchema = z.object({
  stackName: z
    .string()
    .regex(/^[a-z][a-z0-9_-]{0,62}$/)
    .optional(),
  intent: z.string().optional(),
  services: ServicesSchema,
});
export type ResolveDependencyInput = z.infer<typeof ResolveDependencyInputSchema>;

export interface ResolveDependencyResult {
  valid: boolean;
  order: string[];
  missing: Array<{ service: string; dependency: string }>;
  cycles: string[][];
}

function dependencyNames(service: DraftServiceSpec): string[] {
  if (!service.depends_on) return [];
  return Array.isArray(service.depends_on) ? service.depends_on : Object.keys(service.depends_on);
}

export function resolveDependencies(
  services: Record<string, DraftServiceSpec>,
): ResolveDependencyResult {
  const missing: Array<{ service: string; dependency: string }> = [];
  const cycles: string[][] = [];
  const cycleKeys = new Set<string>();
  const order: string[] = [];
  const state = new Map<string, "unvisited" | "visiting" | "visited">();

  for (const name of Object.keys(services)) state.set(name, "unvisited");

  function visit(serviceName: string, path: string[]): void {
    const current = state.get(serviceName);
    if (current === "visited") return;
    if (current === "visiting") {
      const cycleStart = path.indexOf(serviceName);
      if (cycleStart >= 0) {
        const cycle = [...path.slice(cycleStart), serviceName];
        const key = cycle.join("->");
        if (!cycleKeys.has(key)) {
          cycleKeys.add(key);
          cycles.push(cycle);
        }
      }
      return;
    }

    state.set(serviceName, "visiting");
    const deps = dependencyNames(services[serviceName] ?? { image: "unknown" }).sort();
    for (const dep of deps) {
      if (!services[dep]) {
        const edge = { service: serviceName, dependency: dep };
        if (!missing.some((m) => m.service === edge.service && m.dependency === edge.dependency)) {
          missing.push(edge);
        }
        continue;
      }
      visit(dep, [...path, serviceName]);
    }
    state.set(serviceName, "visited");
    order.push(serviceName);
  }

  for (const name of Object.keys(services).sort()) {
    if (state.get(name) === "unvisited") visit(name, []);
  }

  return {
    valid: missing.length === 0 && cycles.length === 0,
    order,
    missing,
    cycles,
  };
}

export const resolveDependency: Tool<ResolveDependencyInput, ResolveDependencyResult> = {
  name: "resolve_dependency",
  description:
    "Validate declared service dependencies, report missing references or cycles, and return dependency-first startup order.",
  inputSchema: ResolveDependencyInputSchema,
  category: "read-only",
  needsPermission: () => false,
  call: async function* (input, ctx): AsyncGenerator<ToolProgress, ResolveDependencyResult> {
    yield { type: "progress", msg: "Resolving service dependencies..." };
    const draft: StackDraft = {
      stackName: input.stackName ?? "validate-temp-stack",
      intent: input.intent ?? "validation only",
      services: input.services,
    };
    const prep = await prepareStackDraft(draft, ctx);
    if (!prep.ok) {
      return {
        valid: false,
        order: [],
        missing: [{ service: "*", dependency: prep.error }],
        cycles: [],
      };
    }
    return resolveDependencies(prep.prepared.services);
  },
};
