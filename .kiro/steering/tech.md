# Tech Stack & Build System

## Runtime & Language

- **Node.js** ≥ 20 (ESM-only — `"type": "module"` in package.json)
- **TypeScript** 5.6 with strict mode, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`
- Path alias `src/*` maps to `./src/*` — always use `src/` imports, never relative `../../`

## Key Libraries

| Purpose | Library |
|---|---|
| Terminal UI | `ink` v5 + `react` v18 (React in the terminal) |
| LLM providers | `@google/generative-ai`, `openai`, `ollama` |
| Docker API | `dockerode` |
| Schema validation | `zod` |
| YAML parsing/emit | `yaml` |
| CLI argument parsing | `commander` |
| Unique IDs | `nanoid` |
| Terminal colours | `chalk` |

## Build Tooling

| Tool | Role |
|---|---|
| `tsup` | Production bundler — outputs to `dist/`, entry: `src/entrypoints/cli.ts` |
| `tsx` | Dev runner with watch mode (`npm run dev`) |
| `biome` | Linter + formatter (replaces ESLint + Prettier) |
| `vitest` | Test runner with `@vitest/coverage-v8` |
| `tsc --noEmit` | Type-checking only (no emit) |

## Common Commands

```bash
# Development (watch mode)
npm run dev
npm run dev -- --provider openai   # with a specific LLM provider

# Build for production
npm run build                      # outputs to dist/

# Testing
npm run test                       # vitest run (single pass)
npm run test:watch                 # vitest watch mode

# Type checking
npm run typecheck                  # tsc --noEmit

# Linting & Formatting
npm run lint                       # biome check
npm run lint:fix                   # biome check --write
npm run format                     # biome format --write

# All checks (typecheck + lint + test)
npm run precheck
```

## Code Style (Biome)

- Indent: 2 spaces
- Line width: 100 characters
- Quotes: double (`"`)
- Semicolons: always
- Applies to `src/` and `tests/` only

## TypeScript Conventions

- Use `import type` for type-only imports
- No default exports — named exports only
- `node:` prefix for Node built-ins (e.g., `import * as fs from "node:fs"`)
- Zod schemas are the source of truth for runtime validation; TypeScript types are derived via `z.infer<>`
- AsyncGenerators are used for streaming tool results (`AsyncGenerator<ToolProgress, TOutput>`)

## Environment Variables

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Google Gemini API key |
| `GEMINI_MODEL` | Gemini model override |
| `OPENAI_API_KEY` | OpenAI API key |
| `OPENAI_BASE_URL` | OpenAI base URL override |
| `OPENAI_MODEL` | OpenAI model override |
| `OLLAMA_HOST` | Ollama server URL |
| `OLLAMA_MODEL` | Ollama model override |
| `DOCKER_AGENT_CONFIG` | Override path to global config JSON |
| `DOCKER_AGENT_PROVIDER` | Override LLM provider at runtime |
