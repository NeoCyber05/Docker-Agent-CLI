# Infra Agent CLI

<p align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-AI%20Agent-orange?logo=langchain&logoColor=white)](https://github.com/langchain-ai/langgraph)
[![Textual](https://img.shields.io/badge/Textual-TUI%20Framework-blueviolet?logo=python&logoColor=white)](https://github.com/Textualize/textual)
[![Docker](https://img.shields.io/badge/Docker-Infrastructure-blue?logo=docker&logoColor=white)](https://www.docker.com/)
[![Pydantic](https://img.shields.io/badge/Pydantic-Validation-red?logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
</p>

Infra Agent CLI (command: `infra-agent`) is a natural-language command-line interface powered by an LLM agent using the ReAct pattern. It manages infrastructure through MCP plugins.

Docker is the first supported plugin, implemented by `docker-mcp-server`. The agent core is domain-neutral: it understands MCP capabilities, pending actions, approval, commit, rollback, commands, context, and resources, and it composes its system prompt from the guidance each connected plugin contributes. Docker-specific planning and execution live in the Docker MCP server. Future infrastructure domains (Kubernetes, cloud providers) plug in the same way.

On startup, `infra-agent` shows a multi-select plugin picker listing the infrastructure MCP servers it knows about (currently Docker). Use ↑/↓ to move, space to toggle, `a` to toggle all, and Enter to connect the chosen plugins for the session. Your choice is remembered for next time.

Instead of writing complex `docker-compose.yaml` files, configuring networks, volumes, and secrets manually, you can ask the Docker plugin in plain language to orchestrate it for you.

---

![Demo](docs/demo.jpg)



## Installation

Clone the repo, install the CLI and the Docker MCP plugin globally, then run it from any directory:

```bash
git clone https://github.com/NeoCyber05/Docker-Agent-CLI.git
cd Docker-Agent-CLI
uv tool install -e ".[docker]"
```

Open a new terminal, then:

```bash
infra-agent
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


### MCP plugin runtime

MCP is mandatory. Docker operations run through `docker-mcp-server` by default. On first use, the CLI creates `~/.docker-agent/mcp_servers.json` with a default `docker` stdio server entry. The optional `label` and `description` fields are shown in the startup plugin picker; add more entries here to make additional infrastructure plugins selectable:

```json
{
  "servers": {
    "docker": {
      "command": "docker-mcp-server",
      "args": [],
      "transport": "stdio",
      "label": "Docker",
      "description": "Deploy and manage Docker Compose stacks"
    }
  }
}
```

Override the config path with `DOCKER_AGENT_MCP_CONFIG`. Disabling values such as `DOCKER_AGENT_MCP=0`, `false`, `off`, or `legacy` fail with a clear error because the old in-process Docker execution path has been removed.

The plugins you pick in the startup selector are remembered in `~/.docker-agent/plugin-selection.json` and pre-ticked on the next launch (override the path with `DOCKER_AGENT_PLUGIN_SELECTION`). Only the selected plugins are connected for the session.

See [docs/mcp-plugin-guide.md](docs/mcp-plugin-guide.md) for the plugin contract used by Docker and future k8s/aws/gcp integrations.

API keys saved via `/connect` are stored separately under `~/.docker-agent/api-keys` on Windows or the OS keychain/secret service on macOS/Linux. Override the Windows storage path with `DOCKER_AGENT_SECRET_DIR`.

---

## CLI commands

### Interactive default

| Command / Option | Description |
| :--- | :--- |
| `infra-agent` | Start the interactive REPL (alias: `docker-agent`) |
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