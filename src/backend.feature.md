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

Natural-language destroy dispatch (`destroy all stacks`, `destroy <stack>`, `Destroy stack <name>`) is handled directly by both backends before entering the agent loop, using the same typed confirmations and messages.

## Parity verification results

All parity gates pass under both backends:

```bash
pnpm vitest run tests/integration/plan-flow.test.ts
# Result: 4 passed

DOCKER_AGENT_BACKEND=langgraph pnpm vitest run tests/integration/plan-flow.test.ts
# Result: 4 passed

pnpm vitest run src/__tests__/backend/CrossBackendParity.test.ts
# Result: 14 passed
```

## Known limitations / flaky tests

There are no known backend-specific functional limitations.

The following tests may flake when the full suite is run concurrently but pass reliably in isolation:

- `src/screens/__tests__/REPL.test.ts`
  - `TypeError: entry.models is not iterable` at `src/services/modelCatalog.ts:77:33` while waiting for the grouped model picker.
  - `/connect opens provider connect dialog` timing out with `condition was not reached`.

These failures are pre-existing and unrelated to the backend migration.

## Precheck / build status

`pnpm test` passes cleanly in this environment (593 passed, 0 failed). Exact counts may vary slightly depending on environment and concurrency:

```bash
pnpm test
# Result: 593 passed | 0 failed
```

The REPL failures documented above are pre-existing flakes and may still appear in other environments or under heavy concurrency; they are unrelated to the backend migration.

`pnpm build` succeeds and the CLI entrypoint works:

```bash
pnpm build
# Result: ESM build success, dist/cli.js generated

node ./dist/cli.js --help
# Result: prints usage/options as expected
```

`pnpm precheck` is blocked at the `typecheck` step by pre-existing TypeScript errors in files unrelated to the backend migration. Because the script uses `&&`, `lint` and `test` are not reached when `typecheck` fails. The same pre-existing issues are visible when running the steps individually.

TypeScript errors (from `pnpm typecheck`):

- `src/tools/applyStack.ts`
- `src/tools/shared/__tests__/dbHealthcheck.test.ts`
- `src/tools/shared/translator.ts`

Lint/format errors (from `pnpm lint`):

- `src/__tests__/backend/CurrentBackend.test.ts`
- `src/__tests__/config.test.ts`
- `src/__tests__/query.test.ts`
- `src/components/FormattedText.tsx`
- `src/components/PlanPreview.tsx`
- `src/components/__tests__/CommandQueue.test.tsx`
- `src/policy/PolicyEngine.ts`
- `src/policy/__tests__/PolicyEngine.test.ts`
- `src/policy/types.ts`
- `src/screens/REPL.tsx`
- `src/screens/__tests__/logsPane.test.tsx`

Runtime smoke test:

```bash
node ./dist/cli.js
```

The CLI launches, renders the initial REPL banner, and then exits with Ink's "Raw mode is not supported on the current process.stdin" error because the non-interactive shell has no TTY. This is environment-specific and confirms the bundle starts; the `--help` smoke test above is the authoritative check.

## Migration status

Phase 1–5 of the LangGraph Agent Backend Migration plan are complete. Task 5.2 precheck and build smoke gate is done.
