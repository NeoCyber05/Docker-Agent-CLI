# ADR 0001: MCP Plugin Boundary

## Status

Accepted; MCP is mandatory and Docker is one plugin implementation.

## Context

The Python CLI used to keep the agent loop, UI/session handling, Docker tools,
Docker state, Docker policy, and Docker runtime dependencies in one package.
That made Docker the implicit core domain even though the target architecture is
a domain-agnostic agent core with Docker, Kubernetes, cloud providers, and other
domains attached as plugins.

The deploy transaction is safety critical. Planning must validate and stage the
desired state without applying it. User-visible action review remains the
approval gate. Applying and rolling back must stay deterministic and auditable.

## Decision

Use MCP as the only plugin boundary and LangGraph as the core control plane. The
core graph owns lifecycle routing: context loading, command routing, model
reasoning, tool policy, tool invocation, human approval, commit, rollback, and
finalize. Docker is one plugin implementation behind that graph.

The core/plugin contract is:

- Tool names are namespaced, for example `docker.list_stacks` or `k8s.deploy`.
- Every plugin exposes `*.capabilities`; the core loads all capability tools and
  merges tool metadata, commands, context tools, commit tools, and rollback tools.
- Model-visible tools can propose or observe; lifecycle tools such as
  `*.commit_action` and `*.rollback_action` stay hidden from the model.
- Mutating tools use a two-phase `PendingAction` contract.
- Pending actions are single-use, session/cwd-bound, time-limited, and revalidated
  before commit.
- Human review uses generic `ActionReviewPayload` with artifacts, warnings,
  secrets, and config files. Compose YAML and stack diffs are Docker artifacts,
  not core fields.
- Rollback is graph-driven: commit returns a rollback action and the graph calls
  the plugin rollback tool.
- Deterministic command shortcuts are plugin-provided command metadata rather
  than Docker-specific regex in core.
- Domain context and resources are provided through generic plugin context tools.

## Consequences

`DOCKER_AGENT_MCP=0` and the native in-process Docker tool loop are removed. If a
user sets a disabling value for `DOCKER_AGENT_MCP`, startup fails with a clear
legacy-path-removed message.

The Docker server exposes the Docker tool surface through namespaced MCP tools.
`docker.deploy_stack` returns a PendingAction, `docker.commit_action` revalidates
and applies the approved deployment transaction, and `docker.rollback_action`
executes rollback transactions returned by failed commits.

Docker-specific tool, state, policy, path, redaction, Docker engine, Compose
runner, image validation, drift, apply, and rollback implementation lives under
`servers/docker-mcp-server/src/docker_mcp_server`. The core package must not
import `docker_mcp_server`, `infra_agent.tools`, `infra_agent.services.docker`,
`infra_agent.policy`, or Docker stack types.
