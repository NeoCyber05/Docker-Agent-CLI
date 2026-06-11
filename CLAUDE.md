# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Docker Agent CLI: a natural-language terminal agent that provisions Docker infrastructure via an LLM using the ReAct (Reason + Act) pattern. ESM-only, Node >= 20, TypeScript + React-in-the-terminal (Ink).

## Commands

```bash
npm run dev                      # interactive REPL (tsx watch src/entrypoints/cli.ts)
npm run dev -- --provider openai # REPL with a specific provider (gemini|openai|ollama)
npm run build                    # tsup bundle -> dist/cli.js (also copies src/prompts -> dist/prompts)
npm test                         # vitest run (full suite)
npm run test:watch               # vitest watch
npm run typecheck                # tsc --noEmit
npm run lint                     # biome check .
npm run lint:fix                 # biome check --write .
npm run precheck                 # typecheck + lint + test — run before committing
```

Single test:
```bash
npx vitest run src/screens/__tests__/REPL.test.ts   # one file
npx vitest run -t "provider: openai"                # by test-name substring
```

Notes:
- Tests use `globals: false` — import `describe/it/expect/vi` explicitly from `vitest`.
- Cross-module imports use the `src/...` path alias (configured in both tsconfig and vitest); prefer it over deep relative paths.
- Repo carries a `pnpm-lock.yaml`; npm scripts above still work. Match whichever lockfile the contributor is using.

## Architecture

Data flows: **CLI args → deps → QueryEngine → ReAct loop (`query`) → provider stream + tool dispatch → LoopEvents → Ink UI / headless stdout.**

### Entry & wiring — `src/entrypoints/cli.ts` → `src/main.ts`
- `parseArgs` (commander) yields commands: `chat` (default, interactive REPL), `status`, `destroy`, `plan`, plus global `--provider` / `--model`.
- `createDeps` builds the dependency bundle: `loadUserConfig` (`~/.docker-agent/config.json`), `resolveProvider` (precedence: `--provider` flag → `DOCKER_AGENT_PROVIDER` env → config), `StateStore`/`SessionStore` (rooted at `./.docker-agent`), `ComposeRunner(cwd)`, `createEngineClient` (dockerode), `createApiKeyStore`, `resolveProviderForRequest`.
- Two execution paths share the same deps + `QueryEngine`:
  - **Interactive**: `renderChatSession` → Ink `render(<REPL>)`.
  - **Headless** (`runHeadless`, used by `status`/`destroy`/`plan`): consumes `engine.query()` events and auto-approves/denies from flags (`--yes`, `--confirm <phrase>`).

### The agent loop — `src/query.ts` `query()` (the heart of the system)
An async generator implementing ReAct:
1. `classifyIntent(lastUser)` picks a `mode`: `plan-once` vs `react` (keyword hint only — `plan_stack` is exposed in both modes so a misroute self-corrects). `maxIterations` = 1 for plan-once, 8 for react.
2. Each iteration: `runProvider` streams provider events; collect assistant `text` + `toolUses`. **No tool uses → turn ends.**
3. Dispatch each tool use, append a `tool` result message, loop again. Hitting `maxIterations` yields an `error` event ("max iterations reached").
4. Special-cased tools inline: `plan_stack` (→ `requestConfirm` raising a `plan_ready` diff), `destroy_all_stacks` (→ `requestTypedConfirm` requiring literal `"DESTROY ALL"`), `remediate_drift`. Generic tools: `findToolByName` → zod `inputSchema.parse` → `needsPermission` → `requestPermission` (with session `allowSet` for always-allow) → `runTool`.

### `QueryEngine` — `src/QueryEngine.ts` (stateful bridge between async loop and UI)
- Owns `messages`, an `AbortController`, and a `pending` map of permission resolvers.
- Bridges the pull-based loop to the event-driven UI via `AsyncQueue` + `deferUserResponse`: the loop `await`s a Promise keyed by a nanoid; the UI later calls `engine.respondTo(id, answer)` to resolve it. `LoopContext` carries the `requestPermission` / `requestConfirm` / `requestTypedConfirm` / `requestSecretsInput` callbacks plus the stores.
- Persists the transcript to `SessionStore` after every turn (powers `/resume`). **Permissions are never resumed** (deliberate safety choice in `loadSession`).

### Providers — `src/services/api`
- `Provider` interface: `stream(params) → AsyncGenerator<ProviderEvent>`, optional `listModels()`. Implementations: `gemini`, `openai`, `ollama`. `resolveProviderForRequest(name)` is the factory.
- Each provider normalizes its vendor stream into uniform `ProviderEvent`s (`text_delta`, `tool_use_start/delta/stop`, `usage`, `message_stop`, `error`) so the loop is vendor-agnostic.
- `toolSchema.ts` converts a Tool's zod `inputSchema` into provider-specific function declarations (`toGeminiFunctionDeclaration` / `toOpenAIFunction`).

### Tools — `src/Tool.ts`, `src/tools/`, registry in `src/tools.ts`
- `Tool` interface: `name`, `description`, `inputSchema` (zod), `category` (`high-level` | `escape-hatch` | `read-only`), `needsPermission(input)`, `call(input, ctx) → AsyncGenerator<ToolProgress, TOutput>`.
- `getToolsForMode("plan-once")` exposes only `plan_stack`; `react` exposes the full set: `plan_stack`, `destroy_stack`, `destroy_all_stacks`, `list_stacks`, `inspect_drift`, `remediate_drift`, `get_stack_status`, `pull_image`, `exec_docker` (escape hatch). `apply_stack` runs via the plan-confirm flow.
- Cross-tool helpers in `src/tools/shared/`: `composeBuilder`, `imageValidation`, `requiredSecrets`.

### State & Docker — `src/state`, `src/services/docker`
- `StateStore` (zod-validated stack YAML + `summary()` injected into the system prompt), `SessionStore` (transcript, `schemaVersion: 1`), `driftDetector` (desired vs running containers), `rollback` (revert a failed apply), `secretRedactor` + `envFile` (secrets isolated in `.docker-agent/secrets/*.env`).
- Docker access: `engineClient` (dockerode), `composeRunner` (`docker compose`), `registryClient`/`imageValidator`/`imageReference` (image-existence checks), `gitGuard`.

### UI — `src/components` (Ink/React), orchestrated by `src/screens/REPL.tsx`
REPL maps `LoopEvent`s to UI: streams assistant text into the message list and raises pending dialogs (`PermissionDialog`, `PlanPreview`, `TypedConfirmDialog`, `SecretsInputDialog`, `ModelPickerDialog`, `ApiKeyInputDialog`). Slash commands (`/stacks`, `/status`, `/provider`, `/model`, `/resume`, …) are handled in `REPL.handleSubmit` before hitting the agent.

## Conventions & gotchas

- **System prompts are markdown**: `src/prompts/{planOnce,react}.md`, read eagerly at import in `context.ts` with a `{{STATE_SUMMARY}}` placeholder. `tsup` copies `src/prompts → dist/prompts` via its `onSuccess` hook — adding a prompt mode means updating both `TEMPLATES` and the build copy.
- **Permission flow is the safety core**: destructive tools (`apply_stack`, `destroy_stack`, `destroy_all_stacks`) are gated. REPL's `DESTRUCTIVE_TOOLS` set is excluded from `--yes` auto-approval, and `destroy_all` additionally requires the typed phrase `DESTROY ALL`.
- **Biome** formatting: 2-space indent, double quotes, semicolons, line width 100 (`src` + `tests` only).
- Regression tests follow a `bugN-*.test.ts` naming pattern under `__tests__/`.

## CodeGraph

A CodeGraph MCP index is configured for structural queries (`codegraph_*` tools). Usage guidance lives in `.claude/CLAUDE.md` — prefer codegraph over grep for "where/what calls X" questions.
