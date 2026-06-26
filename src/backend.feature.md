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

As of Task 3.1, the `langgraph` backend supports all read-only and escape-hatch tools with permission gating matching the `current` backend:

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

For permission-gated tools, `permission_request` is emitted before `tool_call` to maintain parity with `CurrentBackend`.

Mutating lifecycle tools remain unsupported until Phase 4:

- `plan_stack`
- `apply_stack`
- `destroy_stack`
- `destroy_all_stacks`
- `remediate_drift`

## Known limitations

Running the integration plan/apply/destroy suite under the LangGraph backend is expected to fail until Phase 4 implements the `plan_review` node and apply subgraph.

```bash
DOCKER_AGENT_BACKEND=langgraph pnpm vitest run tests/integration/plan-flow.test.ts
```

Failing tests observed (Refactor branch, Task 3.1):

- `deploy flow > nginx: plan -> confirm -> apply via ComposeRunner.forStack`
- `deploy flow > postgres: auto-generates POSTGRES_PASSWORD secret file`
- `deploy flow > destroy_all aborts without typed DESTROY ALL`
- `deploy flow > rollback_started includes runningServices on partial failure`

These failures are caused by `plan_stack`, `apply_stack`, `destroy_stack`, and `destroy_all_stacks` being unsupported on the LangGraph path. The same suite passes under the default `current` backend.
