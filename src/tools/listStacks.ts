import type { Tool, ToolProgress } from "src/Tool";
import type { StackSummary } from "src/types/stack";
import { z } from "zod";

export const ListStacksInputSchema = z.object({});
export type ListStacksInput = z.infer<typeof ListStacksInputSchema>;

export interface ListStacksResult {
  stacks: StackSummary[];
}

export const listStacks: Tool<ListStacksInput, ListStacksResult> = {
  name: "list_stacks",
  description: "List all stacks defined under .docker-agent/stacks/.",
  inputSchema: ListStacksInputSchema,
  category: "read-only",
  needsPermission: () => false,
  call: async function* (_input, ctx): AsyncGenerator<ToolProgress, ListStacksResult> {
    yield { type: "progress", msg: "Listing stacks..." };
    return { stacks: ctx.stateStore.list() };
  },
};
