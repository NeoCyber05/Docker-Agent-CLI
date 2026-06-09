# Requirements Document

## Introduction

This feature bundle adds three operational-safety capabilities to the existing Docker Agent CLI: automatic rollback when a stack apply fails, user-confirmed drift remediation, and resumable chat sessions. The capabilities slot into the established 5-layer architecture and preserve its hard invariants: every Compose operation flows through `ComposeRunner.forStack`, Layer-4 tools and helpers depend only on `ToolContext`, and all user interaction flows through the deferred-resolver/notification event pattern in the orchestration layers. Rollback and remediation reuse the existing `applyStack`/`destroyStack` tools, and resume reuses the existing message and event types.

The goals are: never leave infrastructure in a broken half-applied state after a failed apply, let users safely reconcile detected drift back to desired state with explicit confirmation, and let users continue a previous conversation without re-granting any destructive permissions.

## Glossary

- **Docker_Agent**: The overall CLI application that manages Docker stacks from natural-language commands.
- **Apply_Tool**: The Layer-4 `applyStack` tool that runs Compose `up -d`, extended with a health gate, and returns an `ApplyStackResult`.
- **Health_Gate**: The `verifyHealth` routine inside the Apply_Tool that polls service status until all expected services are running/healthy or a deadline elapses.
- **Rollback_Orchestrator**: The Layer-3 `applyWithRollback` flow that captures known-good state before an apply and restores it after a failed apply.
- **Rollback_Helper**: The Layer-4 `state/rollback.ts` module providing `captureKnownGood` and `planRollback`.
- **Remediation_Orchestrator**: The Layer-3 `handleRemediateDriftToolUse` flow that detects drift, requests confirmation, and re-applies desired state.
- **Remediate_Drift_Tool**: The Layer-4 `remediateDrift` tool that computes a `StackDiff` and serializes desired YAML.
- **Drift_Detector**: The existing `driftDetector` that classifies a stack as `in_sync`, `drift`, `missing`, or `extra`.
- **Session_Store**: The Layer-5 `SessionStore` that persists and loads redacted session transcripts and an index under `.docker-agent/sessions/`.
- **Query_Engine**: The Layer-2 `QueryEngine` that owns the conversation lifecycle, session id, transcript persistence, and rehydration.
- **CLI**: The Layer-1 `main.ts` command entry point, including the `--resume [id]` flag.
- **REPL**: The Layer-1 Ink interface that renders events and repaints resumed transcripts.
- **State_Store**: The existing `StateStore` that records `HistoryEvent` entries.
- **Compose_Runner**: The `ComposeRunner.forStack` gateway, the sole path for all Compose operations.
- **Known_Good**: The on-disk stack definition captured immediately before an apply, used as the restore target.
- **Secret_Pattern**: The `SECRET_KEY_PATTERN` used to identify secret values that must be redacted.

## Requirements

### Requirement 1: Auto-rollback when an apply exits non-zero

**User Story:** As an operator, I want a failed stack apply to be automatically rolled back, so that my infrastructure is never left in a broken half-applied state.

#### Acceptance Criteria

1. WHEN the Apply_Tool returns a non-zero exit code, THE Rollback_Orchestrator SHALL initiate rollback of the affected stack within 5 seconds of receiving the exit code, without requiring operator confirmation.
2. WHEN rollback is initiated for a non-zero exit, THE Rollback_Orchestrator SHALL emit a `rollback_started` event containing the stack name and the reason value `apply_failed`.
3. WHEN a rollback completes for a non-zero exit, THE Rollback_Orchestrator SHALL emit a `rollback_result` event reporting an outcome of either succeeded or failed and the identifier of the Known_Good definition that was restored.
4. WHEN an apply succeeds (Apply_Tool returns exit code 0), THE Rollback_Orchestrator SHALL return a success result and SHALL NOT initiate rollback.
5. WHEN an apply operation begins and before the Apply_Tool overwrites on-disk state, THE Rollback_Orchestrator SHALL capture the Known_Good definition of the affected stack.
6. IF a rollback is initiated for an apply that was updating a stack expected to have a prior Known_Good definition, but neither the live stack file nor the archived definition can be recovered, THEN THE Rollback_Orchestrator SHALL abort the rollback, leave the on-disk state unmodified, emit a `rollback_result` event with an outcome of failed and a restored value of `none`, and advise that manual operator intervention is required.
7. IF the rollback operation itself fails to restore the Known_Good definition, THEN THE Rollback_Orchestrator SHALL emit a `rollback_result` event with an outcome of failed and SHALL indicate that manual operator intervention is required.

### Requirement 2: Auto-rollback when services fail to become healthy

**User Story:** As an operator, I want an apply whose services never become healthy to be rolled back, so that an unhealthy deployment does not remain live.

#### Acceptance Criteria

1. WHEN Compose `up` exits with code zero, THE Health_Gate SHALL poll the status of every expected service (each service declared in the active Compose project) at intervals of 2 seconds until all expected services are healthy or the configured health deadline elapses, where the health deadline defaults to 120 seconds and is constrained to the range 10 to 600 seconds inclusive.
2. THE Health_Gate SHALL consider a service healthy when its container healthcheck reports a healthy status, and SHALL consider a service that defines no healthcheck healthy when its container is in the running state.
3. IF one or more expected services are not healthy when the health deadline elapses, THEN THE Apply_Tool SHALL return a result with `ok` false, `healthy` false, and `unhealthyServices` set to the names of every expected service that is not healthy at that time.
4. WHEN the Apply_Tool returns a result with `healthy` false, THE Rollback_Orchestrator SHALL initiate rollback with reason `unhealthy`.
5. WHEN rollback is initiated for unhealthy services, THE Rollback_Orchestrator SHALL emit a `rollback_started` event whose detail names every unhealthy service.
6. WHEN the Apply_Tool returns a result with `healthy` true, THE Apply_Tool SHALL set `unhealthyServices` to an empty list.
7. IF a rollback initiated with reason `unhealthy` fails to complete, THEN THE Rollback_Orchestrator SHALL emit a rollback-failure event identifying the affected services and SHALL preserve the failed deployment state for operator inspection.
8. THE Apply_Tool SHALL extend its `ApplyStackResult` contract (today comprising `ok`, `exitCode`, `yamlPath`, and `errorOutput`) with the new fields `healthy` and `unhealthyServices`.
9. WHERE the `ApplyStackResult` contract is extended with `healthy` and `unhealthyServices`, THE Docker_Agent SHALL update every existing caller and test of the Apply_Tool to accommodate the extended contract, because the extension is a breaking contract change.

### Requirement 3: Health-gate termination

**User Story:** As an operator, I want the health check to always finish, so that a hung service can never cause the agent to wait forever.

#### Acceptance Criteria

1. WHILE polling service health, THE Health_Gate SHALL return a result no later than the configured deadline, where the deadline is configurable between 10 and 600 seconds inclusive with a default of 120 seconds.
2. WHILE polling service health, THE Health_Gate SHALL query service status at a configured polling interval between 1 and 60 seconds with a default of 2 seconds.
3. IF the configured deadline elapses before all expected services are running or healthy, THEN THE Health_Gate SHALL stop polling and return with `healthy` false and the list of services not yet running or healthy.
4. IF the abort signal is triggered during polling, THEN THE Health_Gate SHALL stop polling and return with `healthy` false within 1 second of the signal.
5. WHEN all expected services are running or healthy before the configured deadline elapses, THE Health_Gate SHALL stop polling and return with `healthy` true.
6. IF a service-status query through the Compose_Runner fails or throws, THEN THE Health_Gate SHALL treat the affected services as not healthy and SHALL continue polling until the configured deadline elapses or the abort signal is triggered.
7. THE Health_Gate SHALL issue every service-status query through the Compose_Runner.

### Requirement 4: Rollback restore strategy selection

**User Story:** As an operator, I want rollback to restore the right prior state, so that updates revert to the last good version and first-time creates are cleaned up.

#### Acceptance Criteria

1. WHEN the apply updated a stack that had a prior Known_Good definition, THE Rollback_Orchestrator SHALL re-apply the Known_Good definition through the Apply_Tool and report the restored state as `previous`.
2. WHEN the apply created the stack for the first time and no prior stack definition existed, THE Rollback_Orchestrator SHALL tear down the partially created stack through the destroy tool and report the restored state as `removed`.
3. WHEN the apply updated an existing stack and a prior Known_Good definition is recoverable from the live stack file or the archived definition, THE Rollback_Helper SHALL produce a `restore_previous` plan.
4. WHEN the apply created the stack for the first time and no prior stack definition existed, THE Rollback_Helper SHALL produce a `teardown_partial` plan.
5. WHEN the live stack file is absent for an updated stack, THE Rollback_Helper SHALL recover the Known_Good definition from the archived definition.
6. WHEN rollback succeeds, THE Rollback_Orchestrator SHALL verify that the running infrastructure matches the prior Known_Good state for an update or contains no running stack resources for a first-time create.
7. IF the rollback action fails to complete through the Apply_Tool or the destroy tool, THEN THE Rollback_Orchestrator SHALL halt rollback, retain the archived Known_Good definition unchanged, and report a rollback failure indicating the restore did not complete.
8. IF the apply updated an existing stack but neither the live stack file nor the archived definition can be recovered, THEN THE Rollback_Helper SHALL produce a `none` plan and report that no recoverable prior state exists.

### Requirement 5: Rollback-itself-fails handling

**User Story:** As an operator, I want a clear signal when rollback cannot complete, so that I know manual intervention is needed and the agent does not loop.

#### Acceptance Criteria

1. IF the restore or teardown action during rollback returns a non-zero result or throws an error, THEN THE Rollback_Orchestrator SHALL emit exactly one `rollback_result` event with `ok` set to false within 5 seconds of the failing action returning or throwing.
2. WHEN a rollback fails, THE Rollback_Orchestrator SHALL return a tool message that states manual intervention is required and identifies which action (restore or teardown) failed.
3. WHEN a rollback fails, THE Rollback_Orchestrator SHALL NOT re-attempt the failed restore or teardown action (zero retries).
4. WHEN a rollback fails, THE Rollback_Orchestrator SHALL terminate the rollback operation after emitting the single `rollback_result` event and SHALL leave any partially restored or torn-down resources in their current state without further modification.
5. IF the apply updated an existing stack and neither a live stack definition nor an archived definition can be recovered, THEN THE Rollback_Helper SHALL produce a plan with type `none`.
6. WHEN the Rollback_Helper produces a plan with type `none`, THE Rollback_Orchestrator SHALL emit a `rollback_result` event with `ok` set to false and `restored` set to `none`, and SHALL NOT attempt any restore or teardown action.

### Requirement 6: Drift remediation detection and confirmation

**User Story:** As an operator, I want to remediate detected drift after reviewing the change, so that I can bring a stack back to desired state safely.

#### Acceptance Criteria

1. WHEN the Remediate_Drift_Tool is invoked for a stack, THE Remediate_Drift_Tool SHALL compute the drift `StackDiff` through the Drift_Detector.
2. WHEN the computed `StackDiff` contains one or more differences, THE Remediate_Drift_Tool SHALL serialize the desired state to YAML.
3. IF the computed `StackDiff` contains zero differences, THEN THE Remediate_Drift_Tool SHALL perform zero Compose operations and SHALL return a message indicating the stack already matches the desired state.
4. WHEN remediation is required for a stack, THE Remediation_Orchestrator SHALL emit a `plan_ready` event presenting the `StackDiff` and the desired YAML for confirmation before performing any Compose operation.
5. WHEN the user approves a remediation, THE Remediation_Orchestrator SHALL re-apply the desired state through the Apply_Tool with rollback protection enabled.
6. IF the Apply_Tool fails during a remediation, THEN THE Remediation_Orchestrator SHALL roll back the stack to its pre-remediation state and SHALL return a message indicating that the remediation failed and the stack was restored.
7. IF the user declines a remediation, THEN THE Remediation_Orchestrator SHALL perform zero Compose operations and SHALL return a message stating the user declined.
8. THE Remediate_Drift_Tool SHALL depend only on `ToolContext` and SHALL NOT request user confirmation or permission directly.

### Requirement 7: Drift remediation status handling

**User Story:** As an operator, I want remediation to behave correctly for each drift status, so that no-op cases do nothing and actionable cases are reconciled.

#### Acceptance Criteria

1. WHEN a remediation request is processed for a stack whose status is `in_sync`, THE Remediation_Orchestrator SHALL execute zero Compose operations and SHALL return a result indicating the stack is already in sync.
2. WHEN a remediation request is processed for a stack whose status is `drift`, THE Remediate_Drift_Tool SHALL set the remediable flag to true.
3. WHEN a remediation request is processed for a stack whose status is `missing`, THE Remediate_Drift_Tool SHALL set the remediable flag to true and SHALL include the complete desired Compose YAML in the result.
4. IF a stack has no desired definition available, THEN THE Remediate_Drift_Tool SHALL set the remediable flag to false and SHALL include a non-empty reason indicating the desired definition is unavailable.
5. WHEN a remediation request is processed for a stack whose status is `extra`, THE Remediation_Orchestrator SHALL re-apply the desired state through the Apply_Tool and SHALL report the count and identifiers of the orphan services that remain after the re-apply.
6. IF a Compose operation fails while remediating a stack, THEN THE Remediation_Orchestrator SHALL stop performing further Compose operations, return a result indicating failure with a non-empty reason, and preserve the recorded desired definition.
7. WHERE one or more orphan services remain after remediating a stack whose status is `extra`, THE Remediation_Orchestrator SHALL report the remediation outcome as not fully clean.
8. THE Remediation_Orchestrator SHALL leave orphan services in place after remediating a stack whose status is `extra`, and THE Remediation_Orchestrator SHALL record automatic orphan removal (for example via `compose --remove-orphans` or a destroy path) as a documented limitation deferred to a possible future feature.

### Requirement 8: Resume a previous session by latest or specific id

**User Story:** As a user, I want to resume a prior conversation, so that I can continue working without losing context.

#### Acceptance Criteria

1. WHEN the user starts chat with `--resume` and no id, THE CLI SHALL request from the Session_Store the single session record whose session-index entry has the latest update timestamp.
2. WHEN the user starts chat with `--resume <id>`, THE CLI SHALL request from the Session_Store the session record whose id exactly equals the provided id.
3. WHEN a session record is loaded, THE Query_Engine SHALL rehydrate the prior messages such that `getMessages` returns the same messages as the loaded record, with identical count and identical order.
4. WHEN a session record is loaded, THE REPL SHALL repaint every message from the loaded record as UI messages in their original order before accepting new input.
5. WHEN the user issues the `/resume <id>` slash command, THE REPL SHALL load the session record whose id exactly equals that id through the Session_Store and rehydrate it within the already-running process without restarting it.
6. WHEN the user submits a new prompt after resuming, THE Query_Engine SHALL append the new messages after the restored messages preserving their original order, and SHALL persist the updated transcript through the Session_Store under the same session id without creating a new session id.
7. WHEN the user issues the `/resume` slash command with no id, THE REPL SHALL load the session record whose session-index entry has the latest update timestamp through the Session_Store and rehydrate it within the already-running process without restarting it.

### Requirement 9: Resume error handling

**User Story:** As a user, I want resume failures to degrade gracefully, so that a missing or corrupt session never blocks me from starting a chat.

#### Acceptance Criteria

1. IF `--resume <id>` names a session that does not exist, THEN THE CLI SHALL print a message indicating the session was not found and SHALL start a fresh chat with empty history.
2. IF `--resume` with no id finds zero previous sessions, THEN THE CLI SHALL print a message indicating no previous session was found and SHALL start a fresh chat with empty history.
3. IF a session file is corrupt or its schema version is not 1, THEN THE Session_Store SHALL return null, emit a warning, and leave the corrupt file unmodified.
4. IF a session file cannot be read due to an I/O or access error, THEN THE Session_Store SHALL return null and SHALL emit a warning.
5. WHEN the Session_Store returns null for a requested resume, THE Docker_Agent SHALL start a fresh chat with empty history within 2 seconds.
6. IF the `/resume` slash command names a session that cannot be loaded, THEN THE REPL SHALL show an error message and SHALL keep the current chat active with its in-memory history unchanged.

### Requirement 10: Transcript persistence and redaction

**User Story:** As a security-conscious user, I want persisted transcripts to exclude secrets, so that resuming a session never exposes sensitive values.

#### Acceptance Criteria

1. WHEN a conversation turn completes, THE Query_Engine SHALL persist the transcript through the Session_Store.
2. THE Session_Store SHALL write each session file atomically by writing to a temporary file and renaming it over the target file.
3. THE Session_Store SHALL maintain exactly one index entry per session id, replacing any prior entry for the same id.
4. WHEN persisting a session record, THE Session_Store SHALL replace every value matching the Secret_Pattern with a redaction placeholder so that no Secret_Pattern value remains in the stored messages.
5. WHEN a session is resumed, THE Session_Store SHALL return only redacted content so that no secret value is exposed.
6. IF a session write fails, THEN THE Session_Store SHALL preserve any prior session file unchanged, emit a warning, and SHALL NOT abort the in-progress turn.

### Requirement 11: Permissions are never resumed

**User Story:** As a security-conscious user, I want a resumed session to re-prompt for permissions, so that destructive approvals are never silently re-granted.

#### Acceptance Criteria

1. WHEN a session record is loaded for resumption, THE Query_Engine SHALL clear the in-memory permission allow-set so that it contains zero entries before any subsequent action is processed.
2. WHEN an action requiring permission occurs after a session is resumed, THE Query_Engine SHALL prompt for permission for that action and SHALL NOT reuse any approval granted before the resume.
3. THE Session_Store SHALL exclude the permission allow-set and all secret input values from every persisted session record.
4. IF a loaded session record contains a permission allow-set or secret input values (for example from a legacy or externally modified record), THEN THE Query_Engine SHALL discard those values and treat the allow-set as empty.

### Requirement 12: History logging of rollback and remediation actions

**User Story:** As an operator, I want rollback and remediation actions recorded in history, so that I can audit what the agent did and in which session.

#### Acceptance Criteria

1. WHEN a rollback operation finishes, THE Rollback_Orchestrator SHALL append exactly one History_Event with action `rollback` that records the rollback reason, the identifier of the restored stack state, a completion timestamp, and a boolean success indicator set to `true`.
2. IF a rollback operation fails before completion, THEN THE Rollback_Orchestrator SHALL append exactly one History_Event with action `rollback` that records the rollback reason, a completion timestamp, a boolean success indicator set to `false`, and a failure reason indicating why the rollback did not complete.
3. WHEN a remediation operation finishes, THE Remediation_Orchestrator SHALL append exactly one History_Event with action `remediate` that records the drift status value evaluated before remediation, a completion timestamp, and a boolean success indicator set to `true`.
4. IF a remediation operation fails before completion, THEN THE Remediation_Orchestrator SHALL append exactly one History_Event with action `remediate` that records the drift status value evaluated before remediation, a completion timestamp, a boolean success indicator set to `false`, and a failure reason indicating why the remediation did not complete.
5. THE State_Store SHALL record the originating session id on each appended History_Event, and WHERE no active session exists at append time, THE State_Store SHALL record an empty session id value.
6. THE State_Store SHALL extend the `HistoryEvent.action` enumeration (today comprising `plan`, `apply`, `destroy`, and `drift_detected`) with the new values `rollback` and `remediate`.

### Requirement 13: Compose-runner invariant and layer isolation

**User Story:** As a maintainer, I want rollback and remediation to honor the architecture invariants, so that the system stays consistent and the CI lint check passes.

#### Acceptance Criteria

1. THE Rollback_Orchestrator SHALL execute every Compose operation (service start/up, teardown/destroy, and service-status query) solely by invoking the Apply_Tool or the destroy tool, and SHALL NOT spawn a Compose process directly nor invoke the Compose_Runner outside the Apply_Tool or destroy tool.
2. THE Remediation_Orchestrator SHALL execute every Compose operation (service start/up, teardown/destroy, and service-status query) solely by invoking the Apply_Tool, and SHALL NOT spawn a Compose process directly nor invoke the Compose_Runner outside the Apply_Tool.
3. THE Rollback_Helper SHALL receive all of its external collaborators through `ToolContext`, and SHALL NOT import, accept as a parameter, or call any function that requests user confirmation, permission, or input.
4. THE Remediate_Drift_Tool SHALL receive all of its external collaborators through `ToolContext`, and SHALL NOT import, accept as a parameter, or call any function that requests user confirmation, permission, or input.
5. THE Compose_Runner SHALL be the only module that spawns a Compose process, and every other module SHALL route all Compose operations through the Compose_Runner.

### Requirement 14: Rollback and remediation user notifications

**User Story:** As a user, I want to see rollback and remediation progress in the REPL, so that I understand what the agent is doing to my infrastructure.

#### Acceptance Criteria

1. WHEN the Rollback_Orchestrator emits a `rollback_started` event, THE REPL SHALL display the stack name and the failure reason value (`apply_failed` or `unhealthy`).
2. WHEN the Rollback_Orchestrator emits a `rollback_result` event with `ok` true, THE REPL SHALL display that the rollback succeeded and the restored value (`previous`, `removed`, or `none`).
3. WHEN the Rollback_Orchestrator emits a `rollback_result` event with `ok` false, THE REPL SHALL display that the rollback failed and SHALL display that manual intervention may be required.
4. WHEN both a `rollback_started` and a `rollback_result` event are emitted for the same rollback, THE REPL SHALL display the `rollback_started` notification before the `rollback_result` notification.
5. WHEN a `rollback_started` event names unhealthy services in its detail, THE REPL SHALL display the names of those services.
6. WHEN remediation requires confirmation, THE REPL SHALL render the desired YAML and the diff using the existing plan preview before the user confirms.
7. WHILE awaiting the user's confirmation response for a remediation, THE REPL SHALL NOT submit a confirmation outcome until the user responds.
8. THE Docker_Agent SHALL extend the `LoopEvent` type with the new notification variants `rollback_started` and `rollback_result`.
