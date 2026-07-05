# ADR 0001: MCP Plugin Boundary

## Status

Accepted; Docker MCP path is now the default runtime.

## Context

The Python CLI used to keep the agent loop, UI/session handling, Docker tools,
Docker state, Docker policy, and Docker runtime dependencies in one package.
That made Docker the implicit core domain even though the target architecture is
a domain-agnostic agent core with Docker, Kubernetes, cloud providers, and other
domains attached as plugins.

The deploy transaction is safety critical. Planning must validate and stage the
desired state without applying it. User-visible plan review remains the approval
gate. Applying and rolling back must stay deterministic and auditable.

## Decision

Use MCP as the plugin boundary and LangGraph as the core control plane. The core
graph owns lifecycle routing: context loading, command routing, model reasoning,
tool policy, tool invocation, human approval, commit, rollback, and finalize.
Docker is one plugin implementation behind that graph.

The core/plugin contract is:

- Tool names are namespaced, for example `docker.list_stacks`.
- Tool metadata carries operation kind, risk, mutating status, confirmation kind,
  commit tool, rollback tool, and model visibility.
- Model-visible tools can propose or observe; lifecycle tools such as
  `*.commit_action`, `*.confirm_action`, and `*.rollback_action` stay hidden from
  the model.
- Mutating tools use a two-phase `PendingAction` contract.
- `PendingAction` values are single-use, session/cwd-bound, time-limited, and
  revalidated before commit.
- Rollback is graph-driven: commit returns a rollback action and the graph calls
  the plugin rollback tool.
- Deterministic command shortcuts are plugin-provided command metadata rather
  than Docker-specific regex in core.
- Domain context is provided through generic plugin context tools.

## Consequences

The MCP path is the default. `DOCKER_AGENT_MCP=0` remains a temporary legacy-path
escape hatch during compatibility cleanup. FastMCP and `langchain-mcp-adapters`
provide the server/client boundary.

The Docker server exposes the Docker tool surface through namespaced MCP tools.
`docker.deploy_stack` returns a PendingAction, `docker.commit_action` revalidates
and applies the approved deployment transaction, and `docker.rollback_action`
executes rollback transactions returned by failed commits. `docker.confirm_action`
remains as a compatibility wrapper around `docker.commit_action`.

Legacy StateGraph files (`engine/graph.py`, old node files, and old state model)
have been removed. Docker-specific server code now lives under
`servers/docker-mcp-server`; the core package only keeps plugin-neutral MCP client
and LangGraph control-plane code. The temporary native compatibility import for
apply-with-rollback lives in `docker_agent.compat.docker_apply`, outside
`engine/nodes`.