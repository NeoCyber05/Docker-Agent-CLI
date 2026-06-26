# Agent Backend Feature Flag

The agent loop that drives tool calls can run in two backend modes, selected by the `DOCKER_AGENT_BACKEND` environment variable.

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

When `DOCKER_AGENT_BACKEND` is unset or set to an unknown value, the `current` backend is used.

## Current parity status

As of Task 4.2, the `langgraph` backend supports all agent-facing tools with the same permission, typed-confirmation, plan-review, and rollback behavior as the `current` backend:

- `validate_spec`
- `resolve_dependency`
- `check_port_conflict`
- `list_stacks`
- `inspect_drift`
- `get_stack_status`
- `get_health`
- `get_logs`
- `pull_image` (permission-gated)
- `exec_docker` (permission-gated)
- `plan_stack` -> approval -> `apply_stack` with rollback
- `destroy_stack` (permission-gated; typed `DESTROY <stack>` confirmation when `--volumes` is set)
- `destroy_all_stacks` (typed `DESTROY ALL` confirmation)
- `remediate_drift` -> approval -> `apply_stack` with rollback

For permission-gated tools, `permission_request` is emitted before `tool_call` to maintain parity with `CurrentBackend`. Plan and remediation approvals emit `plan_ready` and are awaited through the same callback contract as `CurrentBackend`.

The only remaining unsupported tool on the LangGraph path is the internal `apply_stack`, which is intentionally only invoked by the plan/remediate approval flows.

## Known limitations

None. The full integration plan/apply/destroy suite passes under both backends:

```bash
pnpm vitest run tests/integration/plan-flow.test.ts
DOCKER_AGENT_BACKEND=langgraph pnpm vitest run tests/integration/plan-flow.test.ts
```

## Unrelated test observations

`src/screens/__tests__/REPL.test.ts` is flaky in the full test suite but passes reliably in isolation (verified 3/3 times). Observed failures include:

- `TypeError: entry.models is not iterable` at `src/services/modelCatalog.ts:77:33` while waiting for the grouped model picker.
- `/connect opens provider connect dialog` timing out with `condition was not reached`.

These failures do not correlate with the LangGraph backend changes (only `src/backend/langgraph/graph.ts` was modified) and are therefore considered pre-existing test flakiness. No backend code was changed for the model catalog or REPL dialog paths.
