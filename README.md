# Docker Agent CLI

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Node.js Version](https://img.shields.io/badge/node-%3E%3D20-green.svg)](https://nodejs.org/)

An advanced, natural-language Command Line Interface (CLI) powered by an LLM agent using the **ReAct** (Reasoning + Acting) pattern to autonomously manage and provision Docker infrastructure.

Instead of writing complex `docker-compose.yaml` files, configuring networks, volumes, and secrets manually, you can simply ask the Docker Agent in plain English (or Vietnamese) to orchestrate it for you.

---

![Demo](demo.jpg)



## Prerequisites

Before running the Docker Agent CLI, ensure you have:

1. **Node.js** (version `>= 20.x`) installed.
2. **Docker Engine** & **Docker Compose** installed and running on your local machine.
3. Access to an LLM provider:
   - API key for Gemini, OpenAI, or OpenRouter (via env var or `/connect` in the REPL), or
   - A running local Ollama instance.

---

## Quick Start

```bash
git clone https://github.com/NeoCyber05/Docker-Agent-CLI.git
cd Docker-Agent-CLI
npm install
```

---

## Configuration

### Global Config File

Save preferences in a JSON file:

- **Default path**: `~/.docker-agent/config.json`
- **Custom path**: `DOCKER_AGENT_CONFIG` environment variable

#### Configuration schema (`config.json`)

```json
{
  "provider": "gemini",
  "model": "gemini-2.0-flash",
  "defaults": {
    "autoApproveNonDestructive": false
  }
}
```

| Field | Values | Notes |
| :--- | :--- | :--- |
| `provider` | `gemini` \| `openai` \| `openrouter` \| `ollama` | Default LLM provider |
| `model` | string or omitted | Provider-specific model override |
| `defaults.autoApproveNonDestructive` | boolean | Reserved for future use |

### Default models (when not set in config or `--model`)

| Provider | Default model | Env override |
| :--- | :--- | :--- |
| Gemini | `gemini-2.0-flash` | `GEMINI_MODEL` |
| OpenAI | `gpt-4o-mini` | `OPENAI_MODEL` |
| OpenRouter | `openai/gpt-4o-mini` | `OPENROUTER_MODEL` |
| Ollama | `qwen2.5:14b` | `OLLAMA_MODEL` |

### State Directory Structure

The CLI maintains project-local state in `.docker-agent` under your current working directory:

```text
.docker-agent/
├── stacks/              # Saved YAML definitions of active stacks
│   └── .archive/        # Archived configs of destroyed/previous stacks
├── sessions/            # Persisted conversation transcripts
│   ├── index.json       # Session index for /sessions and /resume
│   └── <id>.json        # Individual session records (secrets redacted)
├── locks/               # Process locks to prevent concurrent mutations
├── secrets/             # Per-stack .env files (mode 0700)
├── logs/                # Stack log artifacts
└── history.json         # Audit log (plan, apply, destroy, drift, rollback)
```

API keys saved via `/connect` are stored separately under `~/.docker-agent/api-keys` (Windows) or the OS keychain/secret service (macOS/Linux). Override the Windows storage path with `DOCKER_AGENT_SECRET_DIR`.

---

## CLI Commands

### Interactive (default)

| Command / Option | Description |
| :--- | :--- |
| `docker-agent` | Start the interactive REPL |
| `--provider <name>` | LLM provider: `gemini`, `openai`, `openrouter`, or `ollama` |
| `--model <id>` | Model override for the session |
| `-y, --yes` | Auto-approve non-destructive permissions (destructive tools still gated) |
| `--resume [id]` | Resume the latest session, or a specific session by id (restores transcript and saved model) |
| `-v, --version` | Print version |
| `-h, --help` | Show help |


## Slash Commands (REPL)

Shortcut commands available inside the interactive shell:

| Command | Action |
| :--- | :--- |
| `/help` | List all slash commands |
| `/connect` | Connect a provider (enter API key or configure Ollama) |
| `/model` | Browse models (no args) or set override (`/model openai/gpt-4o`) |
| `/stacks` | List managed stacks |
| `/status <stack>` | Show status and drift for a stack |
| `/yaml <stack>` | Print the stack's Compose YAML |
| `/logs <stack> [service]` | Live-tail stack logs (Esc to stop) |
| `/destroy <stack>` | Tear down one stack |
| `/destroy all` | Tear down all stacks (requires typed `DESTROY ALL` confirmation) |
| `/secrets list <stack>` | List secret env keys (values masked) |
| `/secrets rotate <stack> <service>` | Rotate secrets for a service |
| `/sessions` | List saved sessions (newest first) |
| `/resume` | Resume the most recent session |
| `/resume <id>` | Resume a specific session by id |
| `/clear` | Reset conversation context and clear the screen |
| `/exit` | Exit the REPL (`exit` without slash also works) |

### Keyboard shortcuts (REPL)

| Shortcut | Action |
| :--- | :--- |
| `Ctrl+C` | Cancel the current agent turn |
| `Ctrl+O` | Toggle tool details panel |
| `Ctrl+P` | Open command palette |
| `Ctrl+Q` | Open queue panel (`r` resume, `d` remove, `c` clear) |
| `Enter` (empty input, queue paused) | Resume processing the queue |

---

## Agent Tools

The LLM agent can call these tools during a session:

| Tool | Category | Purpose |
| :--- | :--- | :--- |
| `plan_stack` | high-level | Design a stack and show a plan preview |
| `apply_stack` | high-level | Apply an approved plan (runs after plan confirmation) |
| `destroy_stack` | high-level | Tear down one stack |
| `destroy_all_stacks` | high-level | Tear down all stacks (requires `DESTROY ALL`) |
| `list_stacks` | read-only | List stacks in `.docker-agent/stacks/` |
| `get_stack_status` | read-only | Container status for a stack |
| `get_logs` | read-only | Fetch container logs |
| `get_health` | read-only | Health-check status |
| `inspect_drift` | read-only | Compare desired vs running state |
| `remediate_drift` | high-level | Reconcile drift back to desired state |
| `pull_image` | escape-hatch | Validate and pre-pull a Docker image |
| `exec_docker` | escape-hatch | Run read-only `docker` subcommands (`ps`, `inspect`, `logs`, etc.) |

Destructive tools (`apply_stack`, `destroy_stack`, `destroy_all_stacks`) require explicit approval in the REPL. `--yes` auto-approves only non-destructive permissions.

### Session persistence

- Transcripts are saved to `.docker-agent/sessions/<id>.json` after each turn (secrets redacted).
- Each record stores `createdAt`, `updatedAt`, `cwd`, `provider`, optional `model`, `firstPrompt`, `stackNames`, and the full `messages[]` array.
- `createdAt` is preserved across turns; only `updatedAt` changes on subsequent saves.
- `stackNames` is populated from managed stacks in `.docker-agent/stacks/`.
- Resume (`--resume` or `/resume`) reloads the transcript and restores the saved model override. Pending permission dialogs are **not** resumed.
- If the saved `cwd` differs from the current working directory, a warning is shown in the REPL and on stderr.
- The REPL footer shows the active `session: <id>` for reference.

---

## Prompt Examples

Chat with the agent in plain language:

**Creating stacks**

> *"Tạo một ứng dụng web gồm nginx reverse proxy, 2 backend instance node.js, và một cơ sở dữ liệu postgresql."*
>
> *"Deploy a simple Redis instance exposing port 6379."*

**Inspecting & checking status**

> *"Kiểm tra xem stack my-web-app có bị drift (lệch cấu hình) không?"*
>
> *"What is the status of my database stack?"*

**Destroying infrastructure**

> *"Hãy xoá stack redis-cache đi."*

---

## Development

```bash
npm run dev          # interactive REPL with hot reload
npm run build        # bundle to dist/cli.js (copies prompts/)
```

Install globally after building:

```bash
npm run build
npm link
# Now `docker-agent` is available globally
node dist/cli.js     # or run the built bundle directly
```

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

*Dự án đang trong giai đoạn phát triển hoàn thiện.*