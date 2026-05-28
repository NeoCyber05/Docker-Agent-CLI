# Docker Agent CLI

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Node.js Version](https://img.shields.io/badge/node-%3E%3D20-green.svg)](https://nodejs.org/)

An advanced, natural-language Command Line Interface (CLI) powered by an LLM agent using the **ReAct** (Reasoning + Acting) pattern to autonomously manage and provision Docker infrastructure. 

Instead of writing complex `docker-compose.yaml` files, configuring networks, volumes, and secrets manually, you can simply ask the Docker Agent in plain English (or Vietnamese) to orchestrate it for you.

---

![Demo](demo.jpg)

## Key Features

- **Natural Language Infrastructure Provisioning**: Tell the agent what you want to build (e.g., *"Set up an Nginx reverse proxy routing to two Node.js backend replicas and a PostgreSQL database"*).
- **ReAct Agent Architecture**: The agent reasons through your request, builds a step-by-step execution plan, requests approval, and implements it.
- **Interactive REPL Interface**: A stunning terminal UI built with **Ink** (React in the terminal) that supports syntax highlighting, real-time agent output streaming, and prompt feedback loops.
- **Interactive Execution Plans & Visual Diffs**: Displays a detailed dry-run showing the Docker Compose specification and a visual diff of changed services, ports, volumes, and environment variables *before* any changes are applied.
- **Automated & Secure Secrets Management**: 
  - Automatically identifies necessary credentials (e.g., database passwords, API tokens).
  - Securely prompts you to input them or automatically generates strong random values.
  - Keeps secrets completely decoupled from the main stack configuration.
- **Real-Time Drift Detection**: Actively monitors infrastructure. Compares the desired state (your stack specs) against the actual running state of Docker containers and highlights any configuration drift or manual changes.
- **Multi-Provider LLM Support**: Works seamlessly with **Google Gemini**, **OpenAI GPT**, or local models running via **Ollama**.

---

## 📋 Prerequisites

Before running the Docker Agent CLI, ensure you have:
1. **Node.js** (version `>= 20.x`) installed.
2. **Docker Engine** & **Docker Compose** installed and running on your local machine.
3. Access to an LLM provider (API Key for Gemini/OpenAI, or a running local Ollama instance).

---

## 🚀 Quick Start

### 1. Clone & Install Dependencies
Clone the repository and install the project dependencies:
```bash
git clone https://github.com/NeoCyber05/Docker-Agent-CLI.git
cd Docker-Agent-CLI
npm install
```

### 2. Configure LLM API Keys
Configure the environment variables based on your operating system and the provider you intend to use.

#### Linux / macOS / Git Bash
```bash
# Google Gemini (Default & Recommended)
export GEMINI_API_KEY="your-gemini-api-key"
# Optional: export GEMINI_MODEL="gemini-2.0-flash-exp"

# OpenAI
export OPENAI_API_KEY="your-openai-api-key"
# Optional: export OPENAI_BASE_URL="https://api.openai.com/v1"
# Optional: export OPENAI_MODEL="gpt-4o-mini"

# Ollama (Local)
export OLLAMA_HOST="http://localhost:11434"
# Optional: export OLLAMA_MODEL="qwen2.5:14b"
```

#### Windows (PowerShell)
```powershell
# Google Gemini (Default & Recommended)
$env:GEMINI_API_KEY="your-gemini-api-key"
# Optional: $env:GEMINI_MODEL="gemini-2.0-flash-exp"

# OpenAI
$env:OPENAI_API_KEY="your-openai-api-key"
# Optional: $env:OPENAI_BASE_URL="https://api.openai.com/v1"
# Optional: $env:OPENAI_MODEL="gpt-4o-mini"

# Ollama (Local)
$env:OLLAMA_HOST="http://localhost:11434"
# Optional: $env:OLLAMA_MODEL="qwen2.5:14b"
```

#### Windows (CMD)
```cmd
:: Google Gemini (Default & Recommended)
set GEMINI_API_KEY=your-gemini-api-key
:: Optional: set GEMINI_MODEL=gemini-2.0-flash-exp

:: OpenAI
set OPENAI_API_KEY=your-openai-api-key
:: Optional: set OPENAI_BASE_URL=https://api.openai.com/v1
:: Optional: set OPENAI_MODEL=gpt-4o-mini

:: Ollama (Local)
set OLLAMA_HOST=http://localhost:11434
:: Optional: set OLLAMA_MODEL=qwen2.5:14b
```

### 3. Run in Development Mode
Start the interactive REPL shell:
```bash
npm run dev
```
To launch with a specific provider directly:
```bash
npm run dev -- --provider openai
```

---

## ⚙️ Configuration

### Global Config File
You can save your preferences globally in a JSON configuration file.
- **Default Path**: `~/.docker-agent/config.json`
- **Custom Path**: Defined by the `DOCKER_AGENT_CONFIG` environment variable.

#### Configuration Schema (`config.json`):
```json
{
  "provider": "gemini",
  "model": "gemini-2.0-flash-exp",
  "defaults": {
    "autoApproveNonDestructive": false
  },
  "theme": "dark"
}
```

### State Directory Structure
The CLI maintains local state inside a `.docker-agent` directory in your current working directory.
```text
.docker-agent/
├── stacks/           # Saved YAML configurations of active stacks
│   └── .archive/     # Archived configurations of deleted/previous stacks
├── locks/            # Process locks to prevent concurrent mutations
├── secrets/          # Safely isolated secret values
└── history.json      # Audit log of plans, applies, and actions
```

---

##  CLI Command & Slash Commands

### CLI Command Options
When invoking the CLI globally or from the command line:

| Command / Option | Description |
| :--- | :--- |
| `docker-agent` | Starts the interactive REPL with the default provider. |
| `--provider <name>` | Selects the LLM provider for the session (`gemini` \| `openai` \| `ollama`). |
| `-v, --version` | Prints the current version of the Docker Agent CLI. |
| `-h, --help` | Displays the help menu listing commander options. |

### Slash Commands in REPL
Once inside the interactive REPL shell, you can use these convenient shortcut commands directly:

| Command | Action Description |
| :--- | :--- |
| `/help` | Displays the help menu showing all available slash commands. |
| `/stacks` | Lists all active stacks, their service counts, and last applied timestamps. |
| `/status <stack>` | Shows detailed container statuses and detects drift for a specific stack. |
| `/yaml <stack>` | Prints the generated `docker-compose.yaml` configuration file for a stack. |
| `/destroy <stack>` | Safely stops and tears down the specified stack, removing all volumes (`docker compose down -v`). |
| `/destroy all` | Stops, removes, and tears down all active stacks. |
| `/secrets list <stack>` | Lists all environment secret keys required by a stack (actual values are securely masked). |
| `/secrets rotate <stack> <service>` | Triggers a rotation for the secrets of a specific service in a stack. |
| `/provider <name>` | Dynamically switches the LLM provider for the current session (e.g., `/provider openai`). |
| `/clear` | Resets the conversation context and clears the terminal screen. |
| `/quit` or `/exit` | Gracefully terminates the REPL session and exits the program. |

---

## 💡 Prompt Examples

You can chat with the agent in plain language to carry out infrastructure tasks:

* **Creating Stacks**:
  > *"Tạo một ứng dụng web gồm nginx reverse proxy, 2 backend instance node.js, và một cơ sở dữ liệu postgresql."*
  > *"Deploy a simple Redis instance exposing port 6379."*
* **Inspecting & Checking status**:
  > *"Kiểm tra xem stack my-web-app có bị drift (lệch cấu hình) không?"*
  > *"What is the status of my database stack?"*
* **Destroying Infrastructure**:
  > *"Hãy xoá stack redis-cache đi."*

---

## 🛠️ Development & Testing

We maintain high code quality with automated tests and standard linting tools.

### Compile and Build
Build the production distribution:
```bash
npm run build
```
This generates the compiled JavaScript output inside the `/dist` directory. To run the compiled build, execute `node dist/cli.js` or link it globally:
```bash
npm link
# You can now run `docker-agent` anywhere in your terminal!
```

### Linting and Formatting
We use **Biome** for fast formatting and linting:
```bash
# Lint the codebase
npm run lint

# Automatically fix linting issues
npm run lint:fix

# Format code
npm run format
```

---

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---
*Dự án đang trong giai đoạn phát triển hoàn thiện.*
