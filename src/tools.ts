import type { Tool } from "./Tool";
import { applyStack } from "./tools/applyStack";
import { checkPortConflict } from "./tools/checkPortConflict";
import { destroyAllStacks } from "./tools/destroyAllStacks";
import { destroyStack } from "./tools/destroyStack";
import { execDocker } from "./tools/execDocker";
import { getHealth } from "./tools/getHealth";
import { getLogs } from "./tools/getLogs";
import { getStackStatus } from "./tools/getStackStatus";
import { inspectDrift } from "./tools/inspectDrift";
import { listStacks } from "./tools/listStacks";
import { planStack } from "./tools/planStack";
import { pullImage } from "./tools/pullImage";
import { remediateDrift } from "./tools/remediateDrift";
import { resolveDependency } from "./tools/resolveDependency";
import { validateSpec } from "./tools/validateSpec";

const preflightTools: Tool[] = [
  validateSpec as Tool,
  resolveDependency as Tool,
  checkPortConflict as Tool,
];

/** Tools exposed to the LLM (apply_stack is internal — plan confirm flow only). */
export function getAgentTools(): Tool[] {
  return [
    ...preflightTools,
    planStack as Tool,
    destroyStack as Tool,
    destroyAllStacks as Tool,
    listStacks as Tool,
    inspectDrift as Tool,
    remediateDrift as Tool,
    getStackStatus as Tool,
    getLogs as Tool,
    getHealth as Tool,
    pullImage as Tool,
    execDocker as Tool,
  ];
}

/** Full registry including internal tools (e.g. apply_stack for tests and dispatch). */
export function getAllTools(): Tool[] {
  return [...getAgentTools(), applyStack as Tool];
}