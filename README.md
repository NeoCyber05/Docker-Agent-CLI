# Docker Agent CLI

<p align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-AI%20Agent-orange?logo=langchain&logoColor=white)](https://github.com/langchain-ai/langgraph)
[![Textual](https://img.shields.io/badge/Textual-TUI%20Framework-blueviolet?logo=python&logoColor=white)](https://github.com/Textualize/textual)
[![Docker](https://img.shields.io/badge/Docker-Infrastructure-blue?logo=docker&logoColor=white)](https://www.docker.com/)
[![Pydantic](https://img.shields.io/badge/Pydantic-Validation-red?logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
</p>

Docker Agent CLI is a natural-language command-line interface powered by an LLM agent using the ReAct pattern. It manages infrastructure through MCP plugins.

Docker is the first supported plugin, implemented by `docker-mcp-server`. The agent core is domain-neutral: it understands MCP capabilities, pending actions, approval, commit, rollback, commands, context, and resources. Docker-specific planning and execution live in the Docker MCP server.

Instead of writing complex `docker-compose.yaml` files, configuring networks, volumes, and secrets manually, you can ask the Docker plugin in plain language to orchestrate it for you.

---

![Demo](docs/demo.jpg)

## Prerequisites

Before running the Docker Agent CLI, ensure you have:

1. Python 3.11+ and [uv](https://docs.astral.sh/uv/) or another Python environment manager.
2. Docker Engine and Docker Compose installed and running on your local machine.
3. Access to an LLM provider:
   - API key for Gemini, OpenAI, or OpenRouter via env var or `/connect` in the REPL, or
   - A running local Ollama instance.

---

## Installation

Clone the repo, install the CLI and the Docker MCP plugin globally, then run it from any directory:

```bash
git clone https://github.com/NeoCyber05/Docker-Agent-CLI.git
cd Docker-Agent-CLI
uv tool install -e ".[docker]"
```

Open a new terminal, then:

```bash
docker-agent
```

To upgrade after pulling changes:

```bash
uv tool install --force -e ".[docker]"
```

To remove the global command:

```bash
uv tool uninstall docker-agent
```

---

## Architecture

The package is split into a small agent core and provider-specific MCP plugins:

```text
src/docker_agent/                         # core CLI, UI, session state, LangGraph runtime
  mcp/                                    # MCP config, capability registry, command routing
  engine/langgraph/                       # plugin-neutral graph runtime
  core/                                   # generic action review and loop context

servers/docker-mcp-server/
  src/docker_mcp_server/                  # Docker plugin: tools, policy, state, Compose, rollback
```

The core loads every `*.capabilities` MCP tool from configured servers. Tool names must be namespaced, for example `docker.deploy_stack` or future names such as `k8s.deploy`. Model-visible tools can inspect or propose pending actions. Lifecycle tools such as `*.commit_action`, `*.rollback_action`, context tools, and internal tools are hidden from the model and called only by the graph.

Mutations use a two-phase contract:

1. A plugin tool returns a pending action and generic `ActionReviewPayload`.
2. The user approves the action review.
3. The graph calls the plugin's commit tool.
4. If commit returns a rollback action, the graph calls the plugin rollback tool.

Compose YAML, stack diffs, Docker policy decisions, Docker state files, image validation, and rollback mechanics are Docker plugin artifacts. The core/UI render generic review artifacts and do not special-case Compose.

---

## Configuration

User preferences are stored in `~/.docker-agent/config.json` (override with `DOCKER_AGENT_CONFIG`):

| Field | Purpose |
| :--- | :--- |
| `provider` | LLM provider used on startup (default: `gemini`) |
| `model` | Preferred model id (optional) |
| `defaults` | Policy and approval defaults |

On startup, the REPL loads `provider` and `model` from this file. Choosing a model via `/model` or the model picker saves your choice for the next session.

Provider resolution order: `--provider` flag -> `DOCKER_AGENT_PROVIDER` env -> `config.json` -> `gemini`.

One-time overrides: `--provider` and `--model` apply only to the current launch and do not update `config.json`.

### Provider fallback models

When no explicit model is set in config, CLI flags, or a resumed session, each provider falls back to:

| Provider | Fallback model | Env override |
| :--- | :--- | :--- |
| Gemini | `gemini-2.0-flash` | `GEMINI_MODEL` |
| OpenAI | `gpt-4o-mini` | `OPENAI_MODEL` |
| OpenRouter | `openai/gpt-4o-mini` | `OPENROUTER_MODEL` |
| Ollama | `qwen2.5:14b` | `OLLAMA_MODEL` |

The REPL footer shows this fallback name, not a generic `default` label, when no model override is active.

### State directory structure

Project-local state splits across two directories under your working directory. Core session and log storage remains in `.docker-agent/`; Docker plugin state, desired-state Compose YAML, secrets, locks, and rollback metadata are owned by `docker-mcp-server`. See [docs/docker-agent-directory.md](docs/docker-agent-directory.md) for the full layout, lifecycle, and security notes.

### MCP plugin runtime

MCP is mandatory. Docker operations run through `docker-mcp-server` by default. On first use, the CLI creates `~/.docker-agent/mcp_servers.json` with a default `docker` stdio server entry:

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

Override the config path with `DOCKER_AGENT_MCP_CONFIG`. Disabling values such as `DOCKER_AGENT_MCP=0`, `false`, `off`, or `legacy` fail with a clear error because the old in-process Docker execution path has been removed.

See [docs/mcp-plugin-guide.md](docs/mcp-plugin-guide.md) for the plugin contract used by Docker and future k8s/aws/gcp integrations.

API keys saved via `/connect` are stored separately under `~/.docker-agent/api-keys` on Windows or the OS keychain/secret service on macOS/Linux. Override the Windows storage path with `DOCKER_AGENT_SECRET_DIR`.

---

## CLI commands

### Interactive default

| Command / Option | Description |
| :--- | :--- |
| `docker-agent` | Start the interactive REPL |
| `--provider <name>` | One-time provider override for this launch (`gemini`, `openai`, `openrouter`, `ollama`) |
| `--model <id>` | One-time model override for this launch |
| `-y`, `--yes` | Auto-approve non-destructive permissions; destructive tools stay gated |
| `--resume [id]` | Resume latest session or a specific session id |
| `-v`, `--version` | Print version |
| `-h`, `--help` | Show help |

## Slash commands in the REPL

Shortcut commands available inside the interactive shell:

| Command | Action |
| :--- | :--- |
| `/help` | List all slash commands |
| `/connect` | Connect a provider by entering an API key or configuring Ollama |
| `/model` | Browse models or set and save provider/model |
| `/stacks` | List managed stacks |
| `/status <stack>` | Show status and drift for a stack |
| `/yaml <stack>` | Print the stack's Compose YAML |
| `/logs <stack> [service]` | Live-tail stack logs; `/log` is an alias |
| `/stop <stack> [service...]` | Stop stack containers without removing them |
| `/destroy <stack>` | Tear down one stack |
| `/destroy all` | Tear down all stacks; requires typed confirmation |
| `/secrets list <stack>` | List secret env keys with values masked |
| `/secrets rotate <stack> <service>` | Rotate secrets for a service |
| `/resume` | Open the saved-session picker |
| `/clear` | Reset conversation context and clear the screen |
| `/exit` | Exit the REPL; `exit` without slash also works |

### Keyboard shortcuts in the REPL

| Shortcut | Action |
| :--- | :--- |
| `Ctrl+C` | Cancel the current agent turn |
| `Ctrl+O` | Toggle tool details panel |
| `Ctrl+P` | Open command palette |
| `Ctrl+Q` | Open queue panel (`r` resume, `d` remove, `c` clear) |
| `Enter` with empty input while queue is paused | Resume processing the queue |

---

## Agent tools

The LLM agent invokes model-visible MCP tools during a session to plan, inspect, and propose infrastructure actions. Commit, rollback, context, and other lifecycle tools are hidden from the model and routed by the core graph through plugin capability metadata.

See [docs/agent-tools.md](docs/agent-tools.md) for the Docker tool catalog, approval rules, and session persistence.

---

## Development

Install development dependencies in the repo environment, then run the Python verification stack:

```powershell
uv sync --all-extras --dev
.venv\Scripts\python.exe -m pytest tests\unit\mcp tests\unit\engine\langgraph servers\docker-mcp-server\tests -q
.venv\Scripts\python.exe -m pytest tests servers\docker-mcp-server\tests -q
.venv\Scripts\python.exe -m ruff check src servers\docker-mcp-server tests
```

Build both packages without isolation when the local `.venv` already has the build backend installed:

```powershell
.venv\Scripts\python.exe -m build --no-isolation --outdir C:\tmp\docker-agent-root-build
.venv\Scripts\python.exe -m build --no-isolation --outdir C:\tmp\docker-mcp-server-build servers\docker-mcp-server
```

The isolated `python -m build` path creates temporary build environments and installs backend requirements with pip. If that hangs on Windows, stop the orphaned build processes, ensure `.venv` has working `setuptools` and `wheel`, and rerun the `--no-isolation` commands above.

---

## Prompt examples

Chat with the agent in plain language:

Creating stacks:

> "Create a web app with an nginx reverse proxy, two Node.js backend instances, and PostgreSQL."
>
> "Deploy a simple Redis instance exposing port 6379."

Inspecting and checking status:

> "Check whether stack my-web-app has configuration drift."
>
> "What is the status of my database stack?"

Stopping services without removing:

> "Stop the WordPress container in stack wp-new, but do not delete the stack."
>
> "Stop the redis service in my-cache stack but keep the stack definition."

Destroying infrastructure:

> "Delete the redis-cache stack."

---

## Documentation

| Doc | Contents |
| :--- | :--- |
| [docs/agent-tools.md](docs/agent-tools.md) | Docker MCP tool catalog, approval, session persistence |
| [docs/DOCKER_API_MAPPING.md](docs/DOCKER_API_MAPPING.md) | Tool -> Docker CLI / Engine API mapping |
| [docs/adr/0001-mcp-plugin-boundary.md](docs/adr/0001-mcp-plugin-boundary.md) | Core/plugin boundary ADR |
| [docs/docker-agent-directory.md](docs/docker-agent-directory.md) | `.docker-agent/` state directory structure |
| [docs/mcp-plugin-guide.md](docs/mcp-plugin-guide.md) | MCP capability and pending-action contract |
| [docs/policies.md](docs/policies.md) | Deploy policy system |

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

*This project is under active development.*