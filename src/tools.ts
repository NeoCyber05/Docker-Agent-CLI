import type { Tool } from "./Tool";
import { applyStack } from "./tools/applyStack";
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

export type QueryMode = "plan-once" | "react";

export function getAllTools(): Tool[] {
  return [
    planStack as Tool,
    applyStack as Tool,
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

export function getToolsForMode(mode: QueryMode): Tool[] {
  if (mode === "plan-once") return [planStack as Tool];
  return [
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
