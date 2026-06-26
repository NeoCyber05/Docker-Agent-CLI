# Agent Backend Feature Flag

The agent loop that drives tool calls can run in two backend modes, selected by the `DOCKER_AGENT_BACKEND` environment variable.

## Default backend

`current` remains the default backend. `langgraph` is strictly opt-in via `DOCKER_AGENT_BACKEND=langgraph`.

When `DOCKER_AGENT_BACKEND` is unset or set to an unknown value, `src/backend/AgentBackend.ts` falls back to `current`.

## Selection

| Value       | Backend                                         | Status  |
| ----------- | ----------------------------------------------- | ------- |
| `current`   | Original generator-based loop in `src/query.ts` | default |
| `langgraph` | LangGraph state-graph backend                   | opt-in  |

```bash
# Default path — unchanged behavior
DOCKER_AGENT_BACKEND=current docker-agent ...

# Opt-in to the new LangGraph backend
DOCKER_AGENT_BACKEND=langgraph docker-agent ...
```

## Supported tools under the `langgraph` backend

The `langgraph` backend supports the same set of agent-facing tools as `current`, with identical permission, typed-confirmation, plan-review, and rollback behavior:

- Read-only / advisory tools
  - `validate_spec`
  - `resolve_dependency`
  - `check_port_conflict`
  - `list_stacks`
  - `inspect_drift`
  - `get_stack_status`
  - `get_health`
  - `get_logs`
- Escape-hatch / permission-gated tools
  - `pull_image`
  - `exec_docker`
- Lifecycle / mutating tools
  - `plan_stack` → approval → internal `apply_stack` with rollback
  - `destroy_stack` (permission-gated; typed `DESTROY <stack>` confirmation when `--volumes` is set)
  - `destroy_all_stacks` (typed `DESTROY ALL` confirmation)
  - `remediate_drift` → approval → internal `apply_stack` with rollback

For permission-gated tools, `permission_request` is emitted before `tool_call`, matching `CurrentBackend`. Plan and remediation approvals emit `plan_ready` and are awaited through the same callback contract as `CurrentBackend`.

`apply_stack` is internal and is not exposed to the LLM in either backend. It is only invoked by the `plan_stack` and `remediate_drift` approval flows.

## Parity verification results

All parity gates pass under both backends:

```bash
pnpm vitest run tests/integration/plan-flow.test.ts
# Result: 4 passed

DOCKER_AGENT_BACKEND=langgraph pnpm vitest run tests/integration/plan-flow.test.ts
# Result: 4 passed

pnpm vitest run src/__tests__/backend/CrossBackendParity.test.ts
# Result: 8 passed
```

## Known limitations / flaky tests

There are no known backend-specific functional limitations.

The following tests may flake when the full suite is run concurrently but pass reliably in isolation:

- `src/screens/__tests__/REPL.test.ts`
  - `TypeError: entry.models is not iterable` at `src/services/modelCatalog.ts:77:33` while waiting for the grouped model picker.
  - `/connect opens provider connect dialog` timing out with `condition was not reached`.

These failures are pre-existing and unrelated to the backend migration.

## Migration status

Phase 1–5 of the LangGraph Agent Backend Migration plan are complete.
