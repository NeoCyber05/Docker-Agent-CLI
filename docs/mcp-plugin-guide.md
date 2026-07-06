# MCP Plugin Guide

Docker Agent treats the agent runtime as the core control plane and domain
integrations as MCP plugins. The Docker integration is the first plugin, exposed
by `docker-mcp-server`; Kubernetes, AWS, and GCP should follow the same contract
instead of adding provider-specific nodes to the core graph.


## Repository Layout

The core package is split by responsibility:

```text
src/docker_agent/
  core/                    # framework-neutral agent/domain primitives
  engine/
    adapters/              # LangChain/tool adapters
    langgraph/             # explicit graph runtime, state, model factory, backend wrapper
  mcp/                     # MCP client, config, capability normalization, command routing, approval helpers
```

MCP servers live outside the core package:

```text
servers/
  docker-mcp-server/
    src/docker_mcp_server/
      server.py            # MCP tool registration and lifecycle tools
      tools/               # Docker tool implementation owned by the plugin
      services/docker/     # Docker runtime services owned by the plugin
    tests/unit/            # plugin-owned tests

  k8s-mcp-server/
    src/k8s_mcp_server/
      server.py
      tools/
      services/

  aws-mcp-server/
    src/aws_mcp_server/
      server.py
      tools/
      services/

  gcp-mcp-server/
    src/gcp_mcp_server/
      server.py
      tools/
      services/
```

Future Kubernetes, AWS, and GCP integrations should follow the same server-side
plugin layout, own their provider-specific tools/services, and expose the same
capability lifecycle contract. The core graph
must not add Docker/K8s/AWS/GCP-specific nodes.

## Core Graph

The MCP-enabled runtime is an explicit LangGraph graph:

```text
START -> context_loader -> command_router
command_router -> finalize | reasoning
reasoning -> finalize | tool_policy_gate
tool_policy_gate -> tool_call | human_approval | finalize
tool_call -> reasoning | human_approval | tool_policy_gate
human_approval -> deploy | reasoning | finalize
deploy -> reasoning | finalize | rollback
rollback -> reasoning | finalize
finalize -> END
```

Node responsibilities:

- `context_loader`: load all plugin tools, merged capabilities, model-visible tools, context summary, and resources.
- `command_router`: execute deterministic plugin-declared command shortcuts before LLM reasoning.
- `reasoning`: call the chat model and collect requested tool calls.
- `tool_policy_gate`: block internal tools and unsafe multi-call high-risk batches.
- `tool_call`: invoke model-visible MCP tools and normalize observations or pending actions.
- `human_approval`: collect plan review, typed confirmation, secrets, or permission decisions.
- `deploy`: call the plugin commit tool for an approved pending action.
- `rollback`: call the plugin rollback tool when commit returns a rollback action.
- `finalize`: persist the final transcript state.

## Plugin Contract

Each plugin should expose:

- `*.capabilities`: tool metadata, command metadata, and context endpoints.
- Namespaced model-visible tools such as `docker.deploy_stack` or `k8s.apply_manifest`.
- `*.summarize_context` and optionally `*.list_resources` for domain context.
- `*.commit_action` for approved mutations.
- `*.rollback_action` for graph-driven rollback transactions.
- `*.confirm_action` only as a backward-compatible wrapper around `commit_action`.

Capabilities should identify model-hidden lifecycle tools:

```json
{
  "name": "docker.deploy_stack",
  "namespace": "docker",
  "operation": "plan",
  "risk": "high",
  "mutating": true,
  "confirmation": "plan_review",
  "commit_tool": "docker.commit_action",
  "rollback_tool": "docker.rollback_action"
}
```

Tools with operation `commit`, `confirm`, `rollback`, `context`, or `internal`,
or with `model_visible: false`, are not bound to the model. The graph can call
those tools, but the model cannot request them directly.

## Two-Phase Mutation

Mutating workflows must not apply changes during plan generation. They return a
`pending_confirmation` response containing a single-use PendingAction bound to
`session_id` and `cwd`.

On approval, the graph calls `*.commit_action`. If commit fails after mutation
starts and rollback is available, commit returns:

```json
{
  "status": "error",
  "ok": false,
  "result": "apply failed (...); rollback required.",
  "rollback_action": {
    "id": "rollback-1",
    "tool": "docker.rollback_action"
  }
}
```

The graph then calls `*.rollback_action`. Rollback is therefore a first-class
LangGraph node, not hidden inside deploy.

## Configuration

By default, the core loads MCP servers from:

```text
~/.docker-agent/mcp_servers.json
```

If the file does not exist, the default Docker server entry is created:

```json
{
  "servers": {
    "docker": {
      "command": "docker-mcp-server",
      "args": [],
      "transport": "stdio"
    }
  }
}
```

Use `DOCKER_AGENT_MCP_CONFIG` to point to another config file. MCP is mandatory;
disabling values such as `DOCKER_AGENT_MCP=0`, `false`, or `off` fail because the
legacy in-process Docker path has been removed.
