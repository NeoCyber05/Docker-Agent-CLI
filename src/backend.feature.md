# Agent Backend Feature Flag

The agent loop that drives tool calls can run in two backend modes, selected by the `DOCKER_AGENT_BACKEND` environment variable.

## Selection

| Value      | Backend                                         | Status      |
| ---------- | ----------------------------------------------- | ----------- |
| `current`  | Original generator-based loop in `src/query.ts` | default     |
| `langgraph`| LangGraph state-graph backend                   | opt-in      |

```bash
# Default path — unchanged behavior
DOCKER_AGENT_BACKEND=current docker-agent ...

# Opt-in to the new LangGraph backend
DOCKER_AGENT_BACKEND=langgraph docker-agent ...
```

When `DOCKER_AGENT_BACKEND` is unset or set to an unknown value, the `current` backend is used.

## Current parity status

As of Task 4.1, the `langgraph` backend supports all read-only and escape-hatch tools with permission gating matching the `current` backend, plus the `plan_stack` approval/apply/rollback flow:

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

For permission-gated tools, `permission_request` is emitted before `tool_call` to maintain parity with `CurrentBackend`.

The remaining mutating lifecycle tools are still unsupported on the LangGraph path:

- `destroy_stack`
- `destroy_all_stacks`
- `remediate_drift`

## Known limitations

Running the full integration plan/apply/destroy suite under the LangGraph backend still fails for tools that are explicitly routed to the unsupported path:

```bash
DOCKER_AGENT_BACKEND=langgraph pnpm vitest run tests/integration/plan-flow.test.ts
```

Failing tests observed (Refactor branch, Task 4.1):

- `deploy flow > destroy_all aborts without typed DESTROY ALL`

This failure is caused by `destroy_all_stacks` (and the related `destroy_stack` / `remediate_drift` tools) still being unsupported on the LangGraph path. Plan/apply/rollback cases now pass. The same suite passes under the default `current` backend.
