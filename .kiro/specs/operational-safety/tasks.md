# Implementation Plan: Operational Safety

## Overview

This plan implements three operational-safety capabilities — (A) auto-rollback on apply failure, (B) drift remediation, and (C) resume session — into the existing 5-layer TypeScript/Node 20 codebase. Tasks are ordered to keep the build and test suite green at every step: shared types and the breaking `ApplyStackResult` contract change land first (with all callers/tests updated immediately), then the L4 helpers, then L3 orchestration, then L5 `SessionStore`, then L2 `QueryEngine` resume, then L1 CLI/REPL wiring, and finally the CI invariant extension and full `precheck`.

Hard invariants honored throughout: every Compose operation flows through `ComposeRunner.forStack` (rollback/remediation only re-drive `applyStack`/`destroyStack`); L4 tools and `state/rollback.ts` depend only on `ToolContext` and never call `requestX`; all user interaction is emitted as `LoopEvent`s and answered via the L2/L3 deferred-resolver pattern. Property-based tests (fast-check) cover Properties 6, 7, and 8 from the design.

## Tasks

- [x] 1. Shared types and context foundations
  - [x] 1.1 Add rollback notification variants to `LoopEvent`
    - Edit `src/types/events.ts` to add `rollback_started` (`stackName`, `reason: "apply_failed" | "unhealthy"`, `detail`) and `rollback_result` (`stackName`, `ok`, `restored: "previous" | "removed" | "none"`, optional `detail`) as notification events (no `id`).
    - _Requirements: 1.2, 1.3, 2.5, 14.8_

  - [x] 1.2 Extend `HistoryEvent` action enum and archive read helpers
    - Edit `src/state/StateStore.ts` to extend `HistoryEvent.action` with `"rollback" | "remediate"`.
    - Add `readArchive(stackName)` and `hasArchiveMarker(stackName)` helpers reading `stacks/.archive/<stack>.yaml`, to support known-good recovery.
    - _Requirements: 12.6_

  - [x] 1.3 Thread optional `sessionId` through the tool/loop context
    - Add optional `sessionId?: string` to `ToolContext` in `src/Tool.ts` and confirm it flows via `LoopContext` in `src/loopContext.ts` for history attribution.
    - _Requirements: 12.5_

- [x] 2. Rollback helper (L4, ToolContext-only, no user interaction)
  - [x] 2.1 Implement `state/rollback.ts`
    - Create `src/state/rollback.ts` with `KnownGood`, `RollbackPlan`, `captureKnownGood(stackName, ctx)`, and `planRollback(known, stackName)` per the design pseudocode.
    - `captureKnownGood` reads `ctx.stateStore.read` then `.archive` fallback and classifies into first-time-create / recoverable-update / unrecoverable-update via `existedExpected`/`recoverable`; serializes `previousYaml` only when recoverable.
    - `planRollback` returns exactly one of `restore_previous` / `teardown_partial` / `none`. Depends only on `ToolContext`; performs reads only, no Compose.
    - _Requirements: 4.3, 4.4, 4.5, 4.8, 5.5, 1.6_

  - [ ]* 2.2 Write unit tests for `state/rollback.ts`
    - Create `src/state/__tests__/rollback.test.ts` covering capture cases (live file present, live absent + archive fallback, archive-marker-only unrecoverable, genuine first-time create) and `planRollback` strategy selection (Property 9: strategy completeness, example-based).
    - _Requirements: 4.3, 4.4, 4.5, 4.8, 1.6_

- [x] 3. Apply tool health gate and breaking contract extension
  - [x] 3.1 Add health gate and extend `ApplyStackResult`
    - Edit `src/tools/applyStack.ts`: extend `ApplyStackResult` with `healthy?: boolean` and `unhealthyServices?: string[]`. After `up` exits 0, run `verifyHealth(bound, expectedServices, deadlineMs, abort)` polling `bound.ps({ json: true })`.
    - Use the canonical config: deadline default 120s clamped 10..600s; poll interval default 2s clamped 1..60s. Treat healthcheck `healthy` (or `running` when no healthcheck) as healthy; treat a thrown/failed `ps` as not-healthy and keep polling; stop on deadline or abort.
    - Set `ok = (exitCode === 0 && healthy === true)`; set `unhealthyServices` only when `healthy === false`; write `lastApplied` only on full success.
    - _Requirements: 2.1, 2.2, 2.3, 2.6, 2.8, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [ ]* 3.2 Update existing `applyStack` tests for the extended contract
    - Edit `src/tools/__tests__/applyStack.test.ts` to accommodate the breaking `ApplyStackResult` shape, and add health-gate cases using `MockComposeRunner.ps` returning unhealthy-then-healthy rows; assert `healthy`/`unhealthyServices` and that `ok` reflects health.
    - _Requirements: 2.9, 2.3, 2.6_

  - [ ]* 3.3 Write property test for the health gate
    - Create `src/tools/__tests__/verifyHealth.property.test.ts` using fast-check.
    - **Property 8: Health-gate termination** — for arbitrary `ps` row sequences, `verifyHealth` resolves at/before the deadline or on abort, never looping forever.
    - **Validates: Requirements 3.1, 3.4**

- [x] 4. Checkpoint - contract change settled
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Rollback orchestration (L3, in `src/query.ts`)
  - [x] 5.1 Implement `applyWithRollback` wrapper
    - Add `applyWithRollback(stackName, desiredYaml, scaleOverrides, ctx)` to `src/query.ts`: call `captureKnownGood` before apply, run `applyStack` via `runTool`, and on failure derive `reason` (`unhealthy` vs `apply_failed`) and `detail`.
    - Emit `rollback_started`, run `planRollback`, execute `restore_previous` via `applyStack` / `teardown_partial` via `destroyStack` / `none` as abort (no Compose op), with zero retries on rollback failure.
    - Append one `rollback` `HistoryEvent` (with `ctx.sessionId`), then emit one `rollback_result`. All Compose only via `applyStack`/`destroyStack`.
    - _Requirements: 1.1, 1.4, 1.5, 2.4, 4.1, 4.2, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4, 5.6, 12.1, 12.2, 13.1_

  - [x] 5.2 Wire `applyWithRollback` into the plan-stack apply path
    - Replace the direct `applyStack` call in `handlePlanStackToolUse` with `applyWithRollback` so plan-driven applies are rollback-protected and emit `rollback_started` before `rollback_result`.
    - _Requirements: 1.1, 1.2, 1.3, 14.4_

  - [ ]* 5.3 Write integration tests for the rollback loop
    - Create `tests/integration/rollback-flow.test.ts` with a `replayProvider` that triggers a failing apply (non-zero and unhealthy); assert ordered `rollback_started` then `rollback_result`, the `none`/`previous`/`removed` outcomes, single `rollback_result` on rollback failure, and that the mock only ever saw `forStack(...)` (Property 1 + Property 2, example-based).
    - _Requirements: 1.1, 1.6, 4.1, 4.2, 4.6, 5.1, 5.6_

- [x] 6. Drift remediation tool and flow
  - [x] 6.1 Implement `tools/remediateDrift.ts`
    - Create `src/tools/remediateDrift.ts` with `RemediateDriftInputSchema` (non-empty `stackName`), `RemediateDriftResult` (`diff`, `desiredYaml`, `remediable`, optional `reason`), and the `remediateDrift` tool (category `high-level`, `needsPermission: () => true`).
    - Call `detectDrift`, serialize the desired `StackDefinition` via `yaml.stringify`, set `remediable` true for `drift`/`missing`/`extra`, false with a reason for `in_sync` or missing desired def. Depends only on `ToolContext`; no Compose, no user interaction.
    - _Requirements: 6.1, 6.2, 6.8, 7.2, 7.3, 7.4, 13.4_

  - [ ]* 6.2 Write unit tests for `remediateDrift`
    - Create `src/tools/__tests__/remediateDrift.test.ts` covering `in_sync`/`drift`/`missing`/`extra` classification and the no-desired-def case using `MockDockerEngine` + `StateStore` (Property 3 idempotent in_sync, example-based).
    - _Requirements: 6.3, 7.1, 7.2, 7.3, 7.4_

  - [x] 6.3 Implement `handleRemediateDriftToolUse` and dispatch
    - Add `handleRemediateDriftToolUse(tu, ctx)` to `src/query.ts`: run `remediateDrift`; if not remediable return its reason; otherwise emit `plan_ready` via `requestConfirm` (desired YAML + diff); on decline do zero Compose ops; on approve call `applyWithRollback`.
    - For `extra` status, report remaining orphan count + identifiers and mark outcome not fully clean (no orphan removal). Append one `remediate` `HistoryEvent` (with `ctx.sessionId`). Special-case `remediate_drift` in the tool dispatch loop like `plan_stack`.
    - _Requirements: 6.4, 6.5, 6.6, 6.7, 7.5, 7.6, 7.7, 7.8, 12.3, 12.4, 13.2_

  - [x] 6.4 Register `remediate_drift` in the tool registry
    - Edit `src/tools.ts` to add `remediateDrift` to `getAllTools()` and `getToolsForMode("react")`.
    - _Requirements: 6.1_

  - [ ]* 6.5 Write integration tests for the remediation flow
    - Create `tests/integration/remediation-flow.test.ts` with a replay provider calling `remediate_drift`; assert `plan_ready` confirm is emitted, approve leads to a re-apply, decline leads to zero `up` calls, and `extra` reports orphans as not fully clean (Property 4 + Property 10, example-based).
    - _Requirements: 6.4, 6.7, 7.1, 7.5, 7.7, 7.8_

- [~] 7. Checkpoint - rollback and remediation
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Session persistence store (L5)
  - [x] 8.1 Implement `state/SessionStore.ts`
    - Create `src/state/SessionStore.ts` with `SessionRecord` (schemaVersion 1), `SessionIndexEntry`, and `SessionStore` (`save`, `read`, `latest`, `list`).
    - Write `sessions/<id>.json` atomically (tmp + rename); upsert `sessions/index.json` with exactly one entry per id; on save run messages through the secret redactor keyed by `SECRET_KEY_PATTERN`; tolerate corrupt/wrong-schema/IO-error reads by returning `null` and warning, leaving files unmodified.
    - _Requirements: 8.1, 8.2, 9.3, 9.4, 10.2, 10.3, 10.4, 10.5, 10.6, 11.3_

  - [ ]* 8.2 Write unit tests for `SessionStore`
    - Create `src/state/__tests__/SessionStore.test.ts` covering save/read/latest/list ordering, atomic write, corrupt-file and wrong-schema tolerance (returns null + warns), and index upsert (one entry per id).
    - _Requirements: 9.3, 9.4, 10.2, 10.3, 10.6_

  - [ ]* 8.3 Write property test for transcript secrecy
    - Create `src/state/__tests__/SessionStore.property.test.ts` using fast-check.
    - **Property 6: Transcript secrecy** — for arbitrary env maps containing `SECRET_KEY_PATTERN` keys, the persisted `SessionRecord` JSON never contains the raw secret value and resume returns only redacted content.
    - **Validates: Requirements 10.4, 10.5, 11.3**

- [x] 9. QueryEngine session lifecycle and resume (L2)
  - [x] 9.1 Extend `QueryEngine` with session id, persistence, and rehydration
    - Edit `src/QueryEngine.ts`: add `sessionStore` to `QueryEngineDeps`; generate `sessionId` on construction; add `loadSession(record)` (rehydrate `messages`, continue under same id, clear `pending` and `sessionAllowSet`, discard any persisted allow-set/secret values) and `getMessages()`.
    - Thread `sessionId` into the `LoopContext`; persist the transcript through `SessionStore.save` on turn completion without aborting the turn on save failure.
    - _Requirements: 8.3, 8.6, 10.1, 11.1, 11.2, 11.4, 12.5_

  - [ ]* 9.2 Write unit tests for QueryEngine resume and permission clearing
    - Create `src/__tests__/QueryEngine.resume.test.ts`: persist a transcript, build a new engine, `loadSession`, assert `getMessages()` equals saved messages, allow-set is empty after resume, new turns persist under the same id, and secret values are absent from the serialized record.
    - _Requirements: 8.3, 8.6, 11.1, 11.2, 11.4_

  - [ ]* 9.3 Write property test for resume fidelity
    - Create `src/__tests__/QueryEngine.resume.property.test.ts` using fast-check.
    - **Property 7: Resume fidelity** — for arbitrary `Message[]`, `loadSession(save → read)` round-trips deep-equal and the permission allow-set is empty afterward.
    - **Validates: Requirements 8.3, 11.1**

- [~] 10. Checkpoint - session persistence and resume engine
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. CLI and REPL wiring (L1)
  - [x] 11.1 Add `--resume [id]` flag and SessionStore wiring in `main.ts`
    - Edit `src/main.ts`: add `--resume [id]` to the chat command and `ParsedArgs`; build `SessionStore` in `createDeps`; add `resolveResume(args, sessionStore)` returning the record (`read(id)` or `latest()`), printing "Session not found" / "No previous session found" and starting fresh on null; inject the resumed record into the chat render.
    - _Requirements: 8.1, 8.2, 9.1, 9.2, 9.5_

  - [x] 11.2 Render rollback events and repaint resumed transcript in `REPL.tsx`
    - Edit `src/screens/REPL.tsx`: render `rollback_started` (stack + reason + named unhealthy services) before `rollback_result` (success + restored value, or failure + manual-intervention notice); on resume call `engine.loadSession(record)` once and repaint `record.messages` as `UIMessage[]` in order before accepting input; reuse `PlanPreview` for remediation confirm; handle `/resume [id]` in-process (load via SessionStore + rehydrate + repaint, error message on load failure with current chat unchanged).
    - _Requirements: 8.4, 8.5, 8.7, 9.6, 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7_

  - [x] 11.3 Add `/resume` to slash command suggestions
    - Edit `src/slashCommands.ts` to add a `/resume [id]` suggestion entry.
    - _Requirements: 8.5, 8.7_

  - [ ]* 11.4 Write tests for resume CLI resolution and slash command
    - Create `src/__tests__/main.resume.test.ts` (and extend slash-command tests) covering `resolveResume` not-found / no-previous / success paths and the `/resume` suggestion.
    - _Requirements: 9.1, 9.2, 9.5, 8.5_

- [x] 12. CI invariant coverage and full verification
  - [x] 12.1 Extend the Compose-runner invariant test and run `precheck`
    - Confirm `tests/integration/compose-runner-invariant.test.ts` walks and covers the new files (`state/rollback.ts`, `tools/remediateDrift.ts`, `state/SessionStore.ts`, and the new L3 flows); add an assertion that the new L4 helpers/tools do not reference `requestPermission`/`requestConfirm`/`requestTypedConfirm`/`requestSecretsInput` (Property 5 layer isolation). Run `npm run precheck` (typecheck + biome + vitest) and fix any failures.
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

- [x] 13. Final checkpoint - ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional.
- The breaking `ApplyStackResult` extension (3.1) is immediately followed by updating its tests (3.2) and the L3 caller is migrated to `applyWithRollback` in task 5, keeping the build green.
- Property-based tests (fast-check) cover Properties 6, 7, and 8; Properties 1–5, 9, 10 are validated through unit/integration tests and the CI invariant check.
- Each task references specific requirement sub-clauses for traceability.
- Checkpoints (4, 7, 10, 13) provide incremental validation points.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "8.1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "6.1", "8.2", "8.3"] },
    { "id": 2, "tasks": ["2.2", "3.2", "3.3", "6.2", "6.4", "9.1"] },
    { "id": 3, "tasks": ["5.1", "9.2", "9.3", "11.1", "11.3"] },
    { "id": 4, "tasks": ["5.2"] },
    { "id": 5, "tasks": ["6.3"] },
    { "id": 6, "tasks": ["5.3", "6.5", "11.2", "11.4"] },
    { "id": 7, "tasks": ["12.1"] }
  ]
}
```
