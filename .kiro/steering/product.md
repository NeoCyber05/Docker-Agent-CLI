# Docker Agent CLI — Product Overview

Docker Agent CLI is a natural-language terminal application that lets users provision and manage Docker infrastructure by describing what they want in plain English (or Vietnamese). Instead of writing `docker-compose.yaml` files manually, users chat with an LLM-powered ReAct agent that reasons through the request, builds an execution plan, shows a visual diff, and applies it after approval.

## Core Capabilities

- **Natural language infrastructure** — describe stacks in prose; the agent generates valid Compose YAML
- **ReAct agent loop** — iterative Reasoning + Acting cycle with plan-before-act confirmation
- **Interactive terminal UI** — built on Ink (React in the terminal) with streaming output and real-time diffs
- **Secrets management** — auto-detects credentials, prompts users or auto-generates strong values, stores them in isolated `.env` files decoupled from stack YAML
- **Drift detection** — compares desired state (stack specs) against live Docker containers and reports/remediates drift
- **Multi-provider LLM** — supports Google Gemini (default), OpenAI, and local Ollama models; switchable at runtime

## Primary User Flow

1. User types a request (e.g., "Deploy nginx + two Node backends + PostgreSQL")
2. Agent reasons, generates a `plan_stack` call, shows YAML diff and secret summary
3. User approves; agent calls `apply_stack`, monitors health checks, rolls back on failure
4. User can inspect drift, rotate secrets, or destroy stacks via slash commands or natural language

## Non-Goals

- Not a general-purpose Docker management UI (no image build pipeline, no registry management)
- Not intended for production cloud infra (targets local Docker Engine / Docker Compose)
