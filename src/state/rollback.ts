import type { ToolContext } from "src/Tool";
import type { StackDefinition } from "src/types/stack";
import { stringify as stringifyYaml } from "yaml";

export interface KnownGood {
  /** The recovered prior definition (live file or `.archive` fallback), or null if none was recovered. */
  previous: StackDefinition | null;
  /**
   * True when this apply was an UPDATE that was expected to have a prior definition.
   * False when this apply was a FIRST-TIME CREATE (no prior definition existed or was expected).
   * This distinguishes "did not exist because first-time create" from "expected but unrecoverable".
   */
  existedExpected: boolean;
  /**
   * True when a prior Known_Good definition was actually recovered (from the live stack
   * file or the `.archive/<stack>.yaml` fallback). Always false for a first-time create,
   * and false for an update whose prior state is unrecoverable.
   */
  recoverable: boolean;
  /** YAML serialization of `previous`, ready to feed back into applyStack. Present iff `recoverable`. */
  previousYaml?: string;
}

// Exactly three rollback cases, derived unambiguously from (existedExpected, recoverable):
//   restore_previous : existedExpected && recoverable   (UPDATE with recoverable prior) -> restored = "previous"
//   teardown_partial : !existedExpected                 (FIRST-TIME CREATE)              -> restored = "removed"
//   none             : existedExpected && !recoverable  (UPDATE, prior unrecoverable)    -> restored = "none", abort
export type RollbackPlan =
  | { strategy: "restore_previous"; stackName: string; composeYaml: string }
  | { strategy: "teardown_partial"; stackName: string }
  | { strategy: "none"; reason: string };

/**
 * Capture the current on-disk state BEFORE applyStack overwrites it.
 *
 * Classifies the apply as a first-time create vs an update (and, for an update,
 * whether prior state is recoverable) by consulting StateStore in priority order:
 * 1. Live stack file (`stateStore.read`)
 * 2. Archived definition (`stateStore.readArchive`)
 * 3. Archive marker only (`stateStore.hasArchiveMarker`) — existed but unrecoverable
 * 4. No trace at all — genuine first-time create
 */
export function captureKnownGood(stackName: string, ctx: ToolContext): KnownGood {
  // 1. Try the live stack file.
  const live = ctx.stateStore.read(stackName);
  if (live) {
    return {
      previous: live,
      existedExpected: true,
      recoverable: true,
      previousYaml: stringifyYaml(live),
    };
  }

  // 2. Try the archive fallback.
  const archived = ctx.stateStore.readArchive(stackName);
  if (archived) {
    return {
      previous: archived,
      existedExpected: true,
      recoverable: true,
      previousYaml: stringifyYaml(archived),
    };
  }

  // 3. Archive marker present — stack existed at some point but is unrecoverable.
  if (ctx.stateStore.hasArchiveMarker(stackName)) {
    return { previous: null, existedExpected: true, recoverable: false };
  }

  // 4. Genuine first-time create — no prior definition existed or was expected.
  return { previous: null, existedExpected: false, recoverable: false };
}

/**
 * Decide how to roll back given what existed before the failed apply.
 *
 * Maps (existedExpected, recoverable) to exactly one of three strategies:
 * - `restore_previous`: UPDATE with recoverable prior → re-apply previous YAML
 * - `teardown_partial`: FIRST-TIME CREATE → tear down partial stack
 * - `none`:            UPDATE expected but unrecoverable → abort, advise manual intervention
 */
export function planRollback(known: KnownGood, stackName: string): RollbackPlan {
  if (known.existedExpected && known.recoverable) {
    // UPDATE with recoverable prior → re-apply it (restored = "previous").
    return {
      strategy: "restore_previous",
      stackName,
      composeYaml: known.previousYaml ?? "",
    };
  }

  if (!known.existedExpected) {
    // FIRST-TIME CREATE → tear down the partial stack (restored = "removed").
    return { strategy: "teardown_partial", stackName };
  }

  // UPDATE expected but neither live file nor archive recoverable → abort (restored = "none").
  return {
    strategy: "none",
    reason: "no recoverable prior state (live file and archive both unavailable)",
  };
}
