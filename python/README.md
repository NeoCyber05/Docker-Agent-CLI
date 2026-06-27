# docker-agent (Python)

Natural-language CLI for managing Docker infrastructure via an LLM agent. This is the primary implementation; the TypeScript source has been removed after parity was achieved.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended)
- Docker Engine and Docker Compose
- An LLM provider (Gemini, OpenAI, OpenRouter, or local Ollama)

## Install

```bash
cd python
uv sync
```

## Run

```bash
uv run docker-agent --help
uv run python -m docker_agent
```

## Test

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```

## Configuration

- User config: `~/.docker-agent/config.json` (override with `DOCKER_AGENT_CONFIG`)
- Project policies: `project-policies.yaml` or `.docker-agent/policies.yaml`
- Default backend: LangGraph (`DOCKER_AGENT_BACKEND=langgraph`). Set `DOCKER_AGENT_BACKEND=current` for the legacy loop.

See `../docs/plans/2026-06-27-python-rewrite-ROADMAP.md` for the rewrite history.