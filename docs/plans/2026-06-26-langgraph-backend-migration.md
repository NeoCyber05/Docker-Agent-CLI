# LangGraph Agent Backend Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce an `AgentBackend` abstraction behind `QueryEngine` and migrate the ad-hoc agent loop in `src/query.ts` onto LangGraph (running in-process) without changing any external CLI surface, command, or approval UX.

**Architecture:** Keep `QueryEngine` as the public orchestrator that streams `LoopEvent`s to Ink. Extract a `AgentBackend` interface; `CurrentBackend` wraps the existing `query()` generator verbatim, `LangGraphBackend` rebuilds the same loop as a LangGraph state graph (nodes `agent` / `tools` / `plan_review` / `apply`) using `interrupt()` for human approval. Docker tools (`dockerode`, `ComposeRunner`, `EngineClient`, `applyStack`, `planRollback`) stay untouched and are called by graph nodes via thin adapters. Selection is gated by `DOCKER_AGENT_BACKEND` env var — default stays `current` so existing tests and prod path are unchanged until parity is proven.

**Tech Stack:** TypeScript (Node ≥20), `@langchain/core`, `@langchain/langgraph`, `zod`, `vitest`, `biome`, `tsup`. Existing `ink`/`commander` UI untouched.

---

## Reference — files & contracts the plan touches

- `src/QueryEngine.ts` — public class; `query()` yields `LoopEvent` (line 100). Will delegate to `AgentBackend`.
- `src/query.ts` — current 785-line agent loop, safety gates (`applyWithRollback`, `handlePlanStackToolUse`, typed-confirm flow). Stays as `CurrentBackend` body.
- `src/Tool.ts` — `Tool<TInput,TOutput>` interface, `ToolContext`, `ToolProgress`. Unchanged.
- `src/loopContext.ts` — `LoopContext` (extends `ToolContext`) with 4 human-in-the-loop callbacks + `allowSet`. Unchanged.
- `src/types/events.ts` — `LoopEvent` union. The contract every backend must emit.
- `src/tools.ts` — `getAgentTools()` registry (plan/destroy/dispatch handled specially). Unchanged.
- `src/state/rollback.ts` — pure `captureKnownGood` + `planRollback`. Unchanged.
- `tests/integration/plan-flow.test.ts` — parity oracle; must stay green under both backends.
- `tests/mocks/{mockProvider,mockComposeRunner,mockDockerEngine}.ts` — test infra reused.
- `vitest.config.ts`, `tsup.config.ts` — build/test config. Updated only for new dependency entry.
- `.agents/skills/database-deployment/SKILL.md` etc. — reference for image knowledge; not modified.

## File structure (decomposition decision)

```
src/
  QueryEngine.ts                  # MODIFY: inject AgentBackend instead of calling query() directly
  query.ts                        # UNCHANGED body (becomes CurrentBackend's source)
  backend/
    AgentBackend.ts               # NEW: interface + factory
    CurrentBackend.ts             # NEW: wraps existing query()
    langgraph/
      LangGraphBackend.ts         # NEW: builds graph, drives stream
      graph.ts                    # NEW: state graph definition (nodes/edges)
      nodes/
        agentNode.ts              # NEW: calls provider, returns tool calls
        toolsNode.ts              # NEW: dispatches tools (read-only first)
        planReviewNode.ts         # NEW: plan_stack + interrupt() + applyWithRollback
      adapters/
        toolAdapter.ts            # NEW: Tool -> LangChain tool wrapper
        providerAdapter.ts        # NEW: Provider -> BaseChatModel-like shim
      state.ts                    # NEW: AgentState annotation (messages, iter, allowSet, ...)
      streamBridge.ts             # NEW: langgraph stream -> AsyncGenerator<LoopEvent>
  __tests__/
    backend/
      CurrentBackend.test.ts          # NEW: parity smoke for current backend path
      AgentBackendFactory.test.ts     # NEW: backend selection by env
      langgraph/
        LangGraphBackend.readOnly.test.ts  # NEW: read-only tools parity
        planReview.parity.test.ts     # NEW: plan_stack/apply parity vvs plan-flow.test
      testGraphHarness.ts             # NEW: shared harness (fake provider, engine mocks)
  backend.feature.md              # NEW: short doc explaining env flag
```

Files that **change together** (LangGraph nodes) live together under `backend/langgraph/`. Pure adapters are isolated in `adapters/`. `CurrentBackend` is a one-file shim to keep `query.ts` untouched — zero risk of behavior drift during Phase 1.

---

## Phase 1: AgentBackend interface + CurrentBackend shim

### Task 1.1: Define the AgentBackend interface and factory

**Files:**
- Create: `src/backend/AgentBackend.ts`

- [ ] **Step 1: Write the failing test**

Create `src/__tests__/backend/AgentBackendFactory.test.ts`:

```ts
import { describe, expect, test } from "vitest";
import { createBackend, type AgentBackend } from "src/backend/AgentBackend";

describe("createBackend", () => {
  test("returns CurrentBackend by default", () => {
    const prev = process.env.DOCKER_AGENT_BACKEND;
    delete process.env.DOCKER_AGENT_BACKEND;
    const b = createBackend();
    expect(b.name).toBe("current");
    process.env.DOCKER_AGENT_BACKEND = prev;
  });

  test("returns LangGraphBackend when DOCKER_AGENT_BACKEND=langgraph", () => {
    const prev = process.env.DOCKER_AGENT_BACKEND;
    process.env.DOCKER_AGENT_BACKEND = "langgraph";
    const b = createBackend();
    expect(b.name).toBe("langgraph");
    process.env.DOCKER_AGENT_BACKEND = prev;
  });

  test("falls back to current on unknown value", () => {
    const prev = process.env.DOCKER_AGENT_BACKEND;
    process.env.DOCKER_AGENT_BACKEND = "bogus";
    const b = createBackend();
    expect(b.name).toBe("current");
    process.env.DOCKER_AGENT_BACKEND = prev;
  });
});

describe("AgentBackend interface typing", () => {
  test("AgentBackend has name and query method", () => {
    const b: AgentBackend = {
      name: "stub",
      query: async function* () {},
    };
    expect(b.name).toBe("stub");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm vitest run src/__tests__/backend/AgentBackendFactory.test.ts`
Expected: FAIL — `Cannot find module "src/backend/AgentBackend"`.

- [ ] **Step 3: Write the interface**

Create `src/backend/AgentBackend.ts`:

```ts
import type { LoopEvent } from "src/types/events";
import type { LoopContext } from "src/loopContext";
import type { Provider } from "src/services/api/types";
import type { Message } from "src/types/message";

export interface BackendQueryParams {
  messages: Message[];
  ctx: LoopContext;
  provider: Provider;
  model?: string;
}

export interface AgentBackend {
  readonly name: "current" | "langgraph";
  query(params: BackendQueryParams): AsyncGenerator<LoopEvent, void>;
}

export function createBackend(): AgentBackend {
  const flag = process.env.DOCKER_AGENT_BACKEND ?? "current";
  if (flag === "langgraph") {
    // Lazy import to keep startup fast when defaulting to current.
    // Implementation added in Phase 2.
    const { LangGraphBackend } = require("./langgraph/LangGraphBackend") as {
      LangGraphBackend: new () => AgentBackend;
    };
    return new LangGraphBackend();
  }
  const { CurrentBackend } = require("./CurrentBackend") as {
    CurrentBackend: new () => AgentBackend;
  };
  return new CurrentBackend();
}
```

> Note: uses `require()` lazily so the default startup path (which is `current`) does not pull `@langchain/*` into the bundle unless explicitly requested. We will swap to dynamic `import()` in Task 2.6 once LangGraph is actually installed; for Phase 1 `CurrentBackend` is the only runtime path.

- [ ] **Step 4: Create a stub CurrentBackend so the test compiles**

Create `src/backend/CurrentBackend.ts`:

```ts
import type { AgentBackend, BackendQueryParams } from "./AgentBackend";
import type { LoopEvent } from "src/types/events";

export class CurrentBackend implements AgentBackend {
  readonly name = "current" as const;

  async *query(params: BackendQueryParams): AsyncGenerator<LoopEvent, void> {
    // Body filled in Task 1.2.
    void params;
    yield { type: "error", error: new Error("CurrentBackend not wired") };
  }
}
```

(Note: the test in 1.1 only checks `name`, so this stub passes the factory test.)

- [ ] **Step 5: Run test to verify it passes**

Run: `pnpm vitest run src/__tests__/backend/AgentBackendFactory.test.ts`
Expected: PASS (3 tests). The `langgraph` flag test still passes because `require("./langgraph/LangGraphBackend")` is not triggered when the module is statically present — but it WILL fail when actually constructing. Fix by deferring `langgraph` import until Task 2.6. For now, to keep this test honest, we expect the `langgraph` test to throw at construction and roll it back to `current`.

Revisit Step 1 test — replace the `langgraph` assertion with a skipped guard until Phase 2 lands:

```ts
test.skip("returns LangGraphBackend when DOCKER_AGENT_BACKEND=langgraph", () => {
  const prev = process.env.DOCKER_AGENT_BACKEND;
  process.env.DOCKER_AGENT_BACKEND = "langgraph";
  const b = createBackend();
  expect(b.name).toBe("langgraph");
  process.env.DOCKER_AGENT_BACKEND = prev;
});
```

Re-run: `pnpm vitest run src/__tests__/backend/AgentBackendFactory.test.ts` — PASS (1 skipped).

- [ ] **Step 6: Commit**

```bash
git add src/backend/AgentBackend.ts src/backend/CurrentBackend.ts src/__tests__/backend/AgentBackendFactory.test.ts
git commit -m "feat(backend): add AgentBackend interface + factory"
```

---

### Task 1.2: Wire CurrentBackend to the existing query() function

**Goal:** `CurrentBackend.query()` must yield exactly the same `LoopEvent` stream as `QueryEngine` currently produces by calling `query()` directly. Behavior zero diff.

**Files:**
- Modify: `src/backend/CurrentBackend.ts`
- Create: `src/__tests__/backend/CurrentBackend.test.ts`

- [ ] **Step 1: Write the failing parity test**

Create `src/__tests__/backend/CurrentBackend.test.ts`:

```ts
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { CurrentBackend } from "src/backend/CurrentBackend";
import type { LoopEvent } from "src/types/events";
import type { ProviderEvent } from "src/services/api/types";
import { StateStore } from "src/state/StateStore";
import { MockComposeRunner } from "../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../tests/mocks/mockDockerEngine";
import { afterEach, beforeEach, describe, expect, test } from "vitest";

function fakeProvider(events: ProviderEvent[]) {
  return {
    name: "fake",
    stream: async function* () {
      for (const ev of events) yield ev;
    },
  };
}

describe("CurrentBackend parity", () => {
  let tmp: string;
  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cb-"));
    fs.writeFileSync(path.join(tmp, "project-policies.yaml"), "project: {}");
  });
  afterEach(() => fs.rmSync(tmp, { recursive: true, force: true }));

  test("streams assistant_text + tool_result for a read-only tool call", async () => {
    const ctx = {
      cwd: tmp,
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      abortSignal: new AbortController().signal,
      requestPermission: async () => ({ kind: "approve" as const }),
      requestConfirm: async () => ({ kind: "approve" as const }),
      requestTypedConfirm: async () => ({ kind: "typed_confirm_value" as const, value: "x" }),
      requestSecretsInput: async () => ({ kind: "deny" as const }),
      allowSet: new Set<string>(),
    };
    const events: LoopEvent[] = [];
    const backend = new CurrentBackend();
    for await (const ev of backend.query({
      messages: [{ role: "user", content: "list stacks" }],
      ctx: ctx as never,
      provider: fakeProvider([
        { type: "tool_use_start", id: "t1", name: "list_stacks" },
        { type: "tool_use_delta", id: "t1", argsPartialJson: "{}" },
        { type: "tool_use_stop", id: "t1" },
        { type: "message_stop", stopReason: "tool_use" },
        { type: "text_delta", text: "done" },
        { type: "message_stop", stopReason: "end_turn" },
      ]) as never,
    })) {
      events.push(ev);
    }
    const types = events.map((e) => e.type);
    expect(types).toContain("tool_call");
    expect(types).toContain("tool_result");
    expect(types).toContain("assistant_text");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm vitest run src/__tests__/backend/CurrentBackend.test.ts`
Expected: FAIL — yields `error` event ("CurrentBackend not wired") instead of tool events.

- [ ] **Step 3: Implement CurrentBackend by delegating to query()**

Edit `src/backend/CurrentBackend.ts`:

```ts
import { query } from "src/query";
import type { AgentBackend, BackendQueryParams } from "./AgentBackend";

export class CurrentBackend implements AgentBackend {
  readonly name = "current" as const;

  async *query(params: BackendQueryParams) {
    yield* query(params);
  }
}
```

`query()` already accepts `QueryParams` whose shape is `{ messages, ctx, provider, model? }` — identical to `BackendQueryParams`. No mapping needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm vitest run src/__tests__/backend/CurrentBackend.test.ts`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add src/backend/CurrentBackend.ts src/__tests__/backend/CurrentBackend.test.ts
git commit -m "feat(backend): wire CurrentBackend to existing query loop"
```

---

### Task 1.3: Route QueryEngine through AgentBackend

**Goal:** `QueryEngine.query()` calls `createBackend()` once and delegates to it. All existing `QueryEngine` tests in `src/__tests__/QueryEngine.test.ts` (14 symbols) and `src/__tests__/query.test.ts` (19 symbols) must stay green — they assert on `LoopEvent` stream, so delegation is transparent.

**Files:**
- Modify: `src/QueryEngine.ts:100-165` (the `query()` method body)

- [ ] **Step 1: Capture baseline**

Run: `pnpm test`
Expected: all green. Save the count of passing tests — this is our parity baseline.

- [ ] **Step 2: Refactor QueryEngine**

In `src/QueryEngine.ts`, replace the body of `async *query(userInput: string)` (lines 100-212). Keep message push, logger, abort controller, session persistence logic; only swap the inner `for await (const ev of query({...}))` with the backend.

Change:

```ts
const loopPromise = (async () => {
  try {
    for await (const ev of query({
      messages: this.messages,
      ctx,
      provider: this.provider,
      ...(this.model ? { model: this.model } : {}),
    })) {
      eventQueue.push(ev);
    }
  } catch (err) {
    if (!controller.signal.aborted) {
      eventQueue.push({ type: "error", error: err as Error });
    }
  } finally {
    eventQueue.close();
    for (const [, resolve] of this.pending) resolve({ kind: "deny" });
    this.pending.clear();
  }
})();
```

to:

```ts
const backend = createBackend();
const loopPromise = (async () => {
  try {
    for await (const ev of backend.query({
      messages: this.messages,
      ctx,
      provider: this.provider,
      ...(this.model ? { model: this.model } : {}),
    })) {
      eventQueue.push(ev);
    }
  } catch (err) {
    if (!controller.signal.aborted) {
      eventQueue.push({ type: "error", error: err as Error });
    }
  } finally {
    eventQueue.close();
    for (const [, resolve] of this.pending) resolve({ kind: "deny" });
    this.pending.clear();
  }
})();
```

Add import at top of the file:

```ts
import { createBackend } from "./backend/AgentBackend";
```

(Keep `import { query } from "./query"` for now? No — remove it. `query` is re-exported by `CurrentBackend`. Removing the import prevents accidental drift; the linter will catch any other call site.)

- [ ] **Step 3: Run typecheck**

Run: `pnpm typecheck`
Expected: PASS. If `query` import is flagged as unused elsewhere, keep it only at `CurrentBackend.ts` and remove from `QueryEngine.ts`.

- [ ] **Step 4: Run the full test suite**

Run: `pnpm test`
Expected: identical pass count to Step 1 — zero behavioral change because `CurrentBackend` delegates verbatim.

- [ ] **Step 5: Run integration parity test specifically**

Run: `pnpm vitest run tests/integration/plan-flow.test.ts`
Expected: PASS. This file is our oracle for the plan→apply→rollback path that Phase 4 must preserve.

- [ ] **Step 6: Commit**

```bash
git add src/QueryEngine.ts
git commit -m "refactor(engine): route QueryEngine through AgentBackend"
```

---

## Phase 2: LangGraph minimal backend behind feature flag

### Task 2.1: Add LangGraph dependencies

**Files:**
- Modify: `package.json`
- Modify: `tsup.config.ts` (only if LangGraph needs to be marked external for the CLI bundle)

- [ ] **Step 1: Install runtime deps**

Run:
```bash
pnpm add @langchain/core @langchain/langgraph @langchain/tools
```
Expected: `package.json` updated with three new entries; `pnpm-lock.yaml` updated.

- [ ] **Step 2: Typecheck**

Run: `pnpm typecheck`
Expected: PASS (no usage yet, just types available).

- [ ] **Step 3: Verify build does not regress**

Run: `pnpm build`
Expected: PASS. If `tsup` warns about dynamic import churn, note it for Task 2.6.

- [ ] **Step 4: Commit**

```bash
git add package.json pnpm-lock.yaml
git commit -m "chore(deps): add @langchain/{core,langgraph,tools}"
```

---

### Task 2.2: Define the LangGraph state annotation

**Files:**
- Create: `src/backend/langgraph/state.ts`
- Create: `src/backend/langgraph/state.test.ts`

- [ ] **Step 1: Write the failing test**

Create `src/backend/langgraph/state.test.ts`:

```ts
import { describe, expect, test } from "vitest";
import { AgentState } from "./state";

describe("AgentState annotation", () => {
  test("exposes messages, iter, allowSet, pendingToolResults", () => {
    expect(AgentState.messages).toBeDefined();
    expect(AgentState.iter).toBeDefined();
    expect(AgentState.allowSet).toBeDefined();
    expect(AgentState.pendingToolResults).toBeDefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm vitest run src/backend/langgraph/state.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement state**

Create `src/backend/langgraph/state.ts`:

```ts
import { Annotation } from "@langchain/langgraph";
import type { Message } from "src/types/message";
import type { ToolProgress } from "src/Tool";

export interface PendingToolResult {
  toolUseId: string;
  name: string;
  input: unknown;
  output: unknown;
  isError: boolean;
}

export const AgentState = Annotation.Root({
  messages: Annotation<Message[]>({
    reducer: (a, b) => [...a, ...b],
    default: () => [],
  }),
  iter: Annotation<number>({
    reducer: (_a, b) => b,
    default: () => 0,
  }),
  // session-scoped permission set, mirrors LoopContext.allowSet
  allowSet: Annotation<Set<string>>({
    reducer: (_a, b) => b,
    default: () => new Set(),
  }),
  // tool results produced by toolsNode, drained into messages each loop
  pendingToolResults: Annotation<PendingToolResult[]>({
    reducer: (a, b) => [...a, ...b],
    default: () => [],
  }),
  // progress lines produced by toolsNode for streaming
  progress: Annotation<ToolProgress[]>({
    reducer: (a, b) => [...a, ...b],
    default: () => [],
  }),
  // set when plan_review node has emitted a plan_ready and is waiting for resume
  pendingApproval: Annotation<
    | { stackName: string; composeYaml: string; diff: unknown; configFiles: unknown; autoGeneratedSecrets: unknown }
    | null
  >({
    reducer: (_a, b) => b,
    default: () => null,
  }),
});
```

- [ ] **Step 4: Run test**

Run: `pnpm vitest run src/backend/langgraph/state.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backend/langgraph/state.ts src/backend/langgraph/state.test.ts
git commit -m "feat(langgraph): add AgentState annotation"
```

---

### Task 2.3: Provider adapter — wrap existing Provider as a LangChain-compatible callable

**Why a shim, not BaseChatModel:** our `Provider.stream()` already emits the `ProviderEvent` union (text_delta / tool_use_* / message_stop / usage). Re-implementing it as a `BaseChatModel` would lose streaming fidelity. The `agentNode` will call the `Provider` directly and push events into the graph — the adapter here just packages the input/output types.

**Files:**
- Create: `src/backend/langgraph/adapters/providerAdapter.ts`

- [ ] **Step 1: Implement the adapter**

Create `src/backend/langgraph/adapters/providerAdapter.ts`:

```ts
import type { LoopContext } from "src/loopContext";
import type { Provider, ProviderEvent } from "src/services/api/types";
import type { Message } from "src/types/message";
import { getAgentTools } from "src/tools";
import { buildSystemPrompt } from "src/context";

export interface ProviderTurn {
  text: string;
  toolUses: { id: string; name: string; argsPartial: string }[];
  stopReason: "end_turn" | "tool_use" | "max_tokens";
  usage?: { inputTokens: number; outputTokens: number };
}

export interface StreamedEvent {
  type: "assistant_text" | "usage" | "error";
  text?: string;
  inputTokens?: number;
  outputTokens?: number;
  error?: Error;
}

/**
 * Drive the existing Provider asynchronously, emitting streamed LoopEvent-equivalents
 * through `onEvent`, and returning the structured turn for the graph node.
 */
export async function driveProvider(params: {
  provider: Provider;
  messages: Message[];
  ctx: LoopContext;
  model?: string;
  onEvent: (e: StreamedEvent) => void;
  signal: AbortSignal;
}): Promise<ProviderTurn> {
  const tools = getAgentTools();
  const system = buildSystemPrompt(params.ctx.stateStore.summary());
  const events = params.provider.stream({
    messages: params.messages,
    tools: tools.map((t) => ({
      name: t.name,
      description: t.description,
      inputSchema: t.inputSchema,
    })),
    system,
    ...(params.model ? { model: params.model } : {}),
    signal: params.signal,
  });

  let text = "";
  const toolUses: { id: string; name: string; argsPartial: string }[] = [];
  let stopReason: ProviderTurn["stopReason"] = "end_turn";
  let usage: { inputTokens: number; outputTokens: number } | undefined;

  for await (const ev of events) {
    if (params.signal.aborted) return { text, toolUses, stopReason: "end_turn", usage };
    switch ((ev as ProviderEvent).type) {
      case "text_delta":
        text += (ev as { text: string }).text;
        params.onEvent({ type: "assistant_text", text: (ev as { text: string }).text });
        break;
      case "tool_use_start":
        toolUses.push({ id: (ev as { id: string; name: string }).id, name: (ev as { id: string; name: string }).name, argsPartial: "" });
        break;
      case "tool_use_delta": {
        const d = ev as { id: string; argsPartialJson: string };
        const u = toolUses.find((t) => t.id === d.id);
        if (u) u.argsPartial += d.argsPartialJson;
        break;
      }
      case "tool_use_stop":
        break;
      case "message_stop":
        stopReason = (ev as { stopReason: ProviderTurn["stopReason"] }).stopReason;
        break;
      case "usage":
        usage = { inputTokens: (ev as { inputTokens: number }).inputTokens, outputTokens: (ev as { outputTokens: number }).outputTokens };
        params.onEvent({ type: "usage", ...usage });
        break;
      case "error": {
        const err = (ev as { error: Error }).error;
        params.onEvent({ type: "error", error: err });
        return { text, toolUses, stopReason: "end_turn", usage };
      }
    }
  }
  return { text, toolUses, stopReason, usage };
}
```

- [ ] **Step 2: Typecheck**

Run: `pnpm typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/backend/langgraph/adapters/providerAdapter.ts
git commit -m "feat(langgraph): provider adapter preserves streaming fidelity"
```

---

### Task 2.4: Tool adapter — convert Tool<TIn,TOut> to a plain callable (graph node helper, NOT yet LangChain tool)

**Why not LangChain `tool()` yet:** the current `Tool.call()` returns an `AsyncGenerator<ToolProgress, TOut>` and needs `ToolContext` which is not JSON-serializable. LangChain `tool()` wraps a plain async fn — we'd lose progress streaming. Instead the `toolsNode` invokes our `Tool` interface directly and emits `LoopEvent`s. LangChain-tool wrapping is deferred to Task 3.3 where it is actually needed for the model's tool-call schema; node execution stays native.

**Files:**
- Create: `src/backend/langgraph/adapters/toolAdapter.ts`

- [ ] **Step 1: Implement the adapter**

Create `src/backend/langgraph/adapters/toolAdapter.ts`:

```ts
import type { Tool, ToolProgress } from "src/Tool";
import type { LoopContext } from "src/loopContext";

export interface ToolRun {
  progress: ToolProgress[];
  output: unknown;
  isError: boolean;
}

export async function runTool(
  tool: Tool,
  input: unknown,
  ctx: LoopContext,
): Promise<ToolRun> {
  const progress: ToolProgress[] = [];
  let parsed: unknown = input;
  try {
    parsed = tool.inputSchema.parse(input);
  } catch (err) {
    return {
      progress: [{ type: "progress", msg: `validation failed: ${(err as Error).message}` }],
      output: `validation failed: ${(err as Error).message}`,
      isError: true,
    };
  }
  const gen = tool.call(parsed, ctx);
  let output: unknown;
  while (true) {
    const r = await gen.next();
    if (r.done) {
      output = r.value;
      break;
    }
    progress.push(r.value);
  }
  return { progress, output, isError: false };
}
```

- [ ] **Step 2: Typecheck**

Run: `pnpm typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/backend/langgraph/adapters/toolAdapter.ts
git commit -m "feat(langgraph): tool adapter preserving Tool generator contract"
```

---

### Task 2.5: Minimal graph — agent node + tools node, read-only dispatch

**Goal:** This phase only proves the loop wiring. `toolsNode` dispatches read-only tools (`list_stacks`, `inspect_drift`, `get_stack_status`). Mutating tools (plan_stack, destroy_*, remediate_drift) return an "unsupported in langgraph phase 2" error message so we never break the safety gate on the new path — the env flag means users must opt in, but read-only parity is the Phase 2 acceptance bar.

**Files:**
- Create: `src/backend/langgraph/nodes/agentNode.ts`
- Create: `src/backend/langgraph/nodes/toolsNode.ts`
- Create: `src/backend/langgraph/graph.ts`

- [ ] **Step 1: Implement agentNode**

Create `src/backend/langgraph/nodes/agentNode.ts`:

```ts
import type { LoopContext } from "src/loopContext";
import type { Provider } from "src/services/api/types";
import type { LoopEvent } from "src/types/events";
import { Annotation } from "@langchain/langgraph";
import type { AgentState } from "../state";
import { driveProvider, type StreamedEvent } from "../adapters/providerAdapter";

const MAX_ITERATIONS = 24;

export interface AgentNodeDeps {
  provider: Provider;
  model?: string;
  ctx: LoopContext;
  emit: (ev: LoopEvent) => void;
}

export const agentNode = ({ provider, model, ctx, emit }: AgentNodeDeps) =>
  async (state: typeof AgentState.State) => {
    if (state.iter >= MAX_ITERATIONS) {
      emit({ type: "error", error: new Error(`agent loop reached max iterations (${MAX_ITERATIONS})`) });
      return { iter: state.iter };
    }
    emit({ type: "iteration_start", n: state.iter + 1 });
    const streamed: StreamedEvent[] = [];
    const turn = await driveProvider({
      provider,
      messages: state.messages,
      ctx,
      model,
      signal: ctx.abortSignal,
      onEvent: (e) => {
        streamed.push(e);
        if (e.type === "assistant_text" && e.text) emit({ type: "assistant_text", delta: e.text });
        else if (e.type === "usage") emit({ type: "usage", inputTokens: e.inputTokens!, outputTokens: e.outputTokens! });
        else if (e.type === "error") emit({ type: "error", error: e.error! });
      },
    });
    const blocks: import("src/types/message").AssistantBlock[] = [];
    if (turn.text) blocks.push({ type: "text", text: turn.text });
    for (const tu of turn.toolUses) {
      let input: unknown = {};
      try { input = JSON.parse(tu.argsPartial || "{}"); } catch { /* keep {} */ }
      blocks.push({ type: "tool_use", id: tu.id, name: tu.name, input });
    }
    if (turn.stopReason === "max_tokens") {
      emit({ type: "error", error: new Error("provider response stopped: max tokens reached") });
    }
    return {
      messages: [{ role: "assistant", content: blocks }],
      iter: state.iter + 1,
    };
  };
```

- [ ] **Step 2: Implement toolsNode (read-only only in Phase 2)**

Create `src/backend/langgraph/nodes/toolsNode.ts`:

```ts
import type { LoopContext } from "src/loopContext";
import type { LoopEvent } from "src/types/events";
import { findToolByName } from "src/Tool";
import { getAgentTools } from "src/tools";
import type { AgentState, PendingToolResult } from "../state";
import { runTool } from "../adapters/toolAdapter";

const READ_ONLY_ALLOWLIST = new Set(["list_stacks", "inspect_drift", "get_stack_status", "get_health", "get_logs"]);

export interface ToolsNodeDeps {
  ctx: LoopContext;
  emit: (ev: LoopEvent) => void;
}

export const toolsNode = ({ ctx, emit }: ToolsNodeDeps) =>
  async (state: typeof AgentState.State) => {
    const assistantMsg = state.messages[state.messages.length - 1];
    if (!assistantMsg || assistantMsg.role !== "assistant") return {};
    const toolUses = (assistantMsg.content as Array<{ type: string; id?: string; name?: string; input?: unknown }>)
      .filter((b) => b.type === "tool_use");
    const results: PendingToolResult[] = [];
    for (const tu of toolUses) {
      if (ctx.abortSignal.aborted) break;
      emit({ type: "tool_call", name: tu.name!, input: tu.input });
      if (!READ_ONLY_ALLOWLIST.has(tu.name!)) {
        emit({ type: "tool_result", name: tu.name!, output: "tool not supported in langgraph backend (phase 2)" });
        results.push({ toolUseId: tu.id!, name: tu.name!, input: tu.input, output: "tool not supported in langgraph backend (phase 2)", isError: true });
        continue;
      }
      const tool = findToolByName(getAgentTools(), tu.name!);
      if (!tool) {
        results.push({ toolUseId: tu.id!, name: tu.name!, input: tu.input, output: `unknown tool: ${tu.name}`, isError: true });
        continue;
      }
      const run = await runTool(tool, tu.input, ctx);
      for (const p of run.progress) emit({ type: "tool_progress", msg: p.msg });
      emit({ type: "tool_result", name: tu.name!, output: run.output });
      results.push({ toolUseId: tu.id!, name: tu.name!, input: tu.input, output: run.output, isError: run.isError });
    }
    const toolMessages = results.map((r) => ({
      role: "tool" as const,
      toolUseId: r.toolUseId,
      content: typeof r.output === "string" ? r.output : JSON.stringify(r.output),
      isError: r.isError,
    }));
    return { messages: toolMessages, pendingToolResults: results };
  };
```

- [ ] **Step 3: Implement the graph builder**

Create `src/backend/langgraph/graph.ts`:

```ts
import { StateGraph, END } from "@langchain/langgraph";
import { AgentState } from "./state";
import { agentNode, type AgentNodeDeps } from "./nodes/agentNode";
import { toolsNode, type ToolsNodeDeps } from "./nodes/toolsNode";

export interface GraphDeps extends AgentNodeDeps, ToolsNodeDeps {
  model?: string;
  provider: AgentNodeDeps["provider"];
  ctx: AgentNodeDeps["ctx"];
  emit: AgentNodeDeps["emit"];
}

export function buildGraph(deps: GraphDeps) {
  const g = new StateGraph(AgentState)
    .addNode("agent", agentNode({ provider: deps.provider, model: deps.model, ctx: deps.ctx, emit: deps.emit }))
    .addNode("tools", toolsNode({ ctx: deps.ctx, emit: deps.emit }))
    .addEdge("__start__", "agent")
    .addConditionalEdges("agent", (state: typeof AgentState.State) => {
      const last = state.messages[state.messages.length - 1];
      const hasToolUse = last?.role === "assistant" &&
        Array.isArray(last.content) &&
        (last.content as Array<{ type: string }>).some((b) => b.type === "tool_use");
      if (!hasToolUse) return END;
      if (state.iter >= 24) return END;
      return "tools";
    })
    .addEdge("tools", "agent");
  return g.compile();
}
```

- [ ] **Step 4: Typecheck**

Run: `pnpm typecheck`
Expected: PASS. If `@langchain/langgraph` types complain about reducer signatures, narrow the annotation (the `default: () => []` form is the documented one).

- [ ] **Step 5: Commit**

```bash
git add src/backend/langgraph/nodes/ src/backend/langgraph/graph.ts
git commit -m "feat(langgraph): minimal agent+tools graph with read-only allowlist"
```

---

### Task 2.6: LangGraphBackend driver — wire graph -> AsyncGenerator<LoopEvent>

**Files:**
- Create: `src/backend/langgraph/LangGraphBackend.ts`
- Create: `src/backend/langgraph/LangGraphBackend.test.ts`
- Modify: `src/backend/AgentBackend.ts` (un-skip the langgraph factory test from Task 1.1)
- Modify: `src/__tests__/backend/AgentBackendFactory.test.ts` (un-skip)

- [ ] **Step 1: Write the failing test**

Create `src/backend/langgraph/LangGraphBackend.test.ts`:

```ts
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { LangGraphBackend } from "./LangGraphBackend";
import type { LoopEvent } from "src/types/events";
import type { ProviderEvent } from "src/services/api/types";
import { StateStore } from "src/state/StateStore";
import { MockComposeRunner } from "../../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../../tests/mocks/mockDockerEngine";
import { afterEach, beforeEach, describe, expect, test } from "vitest";

function fakeProvider(events: ProviderEvent[]) {
  return { name: "fake", stream: async function* () { for (const ev of events) yield ev; } };
}

describe("LangGraphBackend read-only smoke", () => {
  let tmp: string;
  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "lg-"));
    fs.writeFileSync(path.join(tmp, "project-policies.yaml"), "project: {}");
  });
  afterEach(() => fs.rmSync(tmp, { recursive: true, force: true }));

  test("list_stacks -> tool_call + tool_result + assistant_text", async () => {
    const ctx = {
      cwd: tmp,
      stateStore: new StateStore(tmp),
      dockerEngine: new MockDockerEngine() as never,
      composeRunner: new MockComposeRunner(tmp) as never,
      abortSignal: new AbortController().signal,
      requestPermission: async () => ({ kind: "approve" as const }),
      requestConfirm: async () => ({ kind: "approve" as const }),
      requestTypedConfirm: async () => ({ kind: "typed_confirm_value" as const, value: "x" }),
      requestSecretsInput: async () => ({ kind: "deny" as const }),
      allowSet: new Set<string>(),
    };
    const events: LoopEvent[] = [];
    const backend = new LangGraphBackend();
    for await (const ev of backend.query({
      messages: [{ role: "user", content: "list stacks" }],
      ctx: ctx as never,
      provider: fakeProvider([
        { type: "tool_use_start", id: "t1", name: "list_stacks" },
        { type: "tool_use_delta", id: "t1", argsPartialJson: "{}" },
        { type: "tool_use_stop", id: "t1" },
        { type: "message_stop", stopReason: "tool_use" },
        { type: "text_delta", text: "no stacks" },
        { type: "message_stop", stopReason: "end_turn" },
      ]) as never,
    })) {
      events.push(ev);
    }
    const types = events.map((e) => e.type);
    expect(types).toContain("iteration_start");
    expect(types).toContain("tool_call");
    expect(types).toContain("tool_result");
    expect(types).toContain("assistant_text");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm vitest run src/backend/langgraph/LangGraphBackend.test.ts`
Expected: FAIL — module not found (`LangGraphBackend`).

- [ ] **Step 3: Implement LangGraphBackend**

Create `src/backend/langgraph/LangGraphBackend.ts`:

```ts
import type { AgentBackend, BackendQueryParams } from "../AgentBackend";
import type { LoopEvent } from "src/types/events";
import { buildGraph } from "./graph";
import { MemorySaver } from "@langchain/langgraph";

export class LangGraphBackend implements AgentBackend {
  readonly name = "langgraph" as const;

  async *query(params: BackendQueryParams): AsyncGenerator<LoopEvent, void> {
    const queue: LoopEvent[] = [];
    let resolveOne: ((v: LoopEvent | "done") => void) | null = null;
    const emit = (ev: LoopEvent) => {
      if (resolveOne) {
        const r = resolveOne;
        resolveOne = null;
        r(ev);
      } else {
        queue.push(ev);
      }
    };

    const graph = buildGraph({
      provider: params.provider,
      ctx: params.ctx,
      model: params.model,
      emit,
    });

    const initial = { messages: params.messages, iter: 0, allowSet: params.ctx.allowSet, pendingToolResults: [], progress: [], pendingApproval: null };
    const stream = await graph.stream(initial, {
      recursionLimit: 50,
      streamMode: ["values"],
      checkpoints: new MemorySaver(),
    });

    let done = false;
    const streamDone = (async () => {
      try {
        for await (const _chunk of stream) {
          // events already pushed by node callbacks via emit()
          void _chunk;
          if (params.ctx.abortSignal.aborted) break;
        }
      } catch (err) {
        if (!params.ctx.abortSignal.aborted) {
          emit({ type: "error", error: err as Error });
        }
      } finally {
        done = true;
        if (resolveOne) {
          const r = resolveOne;
          resolveOne = null;
          r("done");
        }
      }
    })();

    while (!done) {
      const ev = queue.shift();
      if (ev) {
        yield ev;
      } else {
        const next = await new Promise<LoopEvent | "done">((r) => { resolveOne = r; });
        if (next === "done") break;
        yield next;
      }
    }
    await streamDone;
  }
}
```

- [ ] **Step 4: Update AgentBackend factory to use dynamic import (lazy, bundle-friendly)**

Edit `src/backend/AgentBackend.ts`:

```ts
import type { LoopEvent } from "src/types/events";
import type { LoopContext } from "src/loopContext";
import type { Provider } from "src/services/api/types";
import type { Message } from "src/types/message";

export interface BackendQueryParams {
  messages: Message[];
  ctx: LoopContext;
  provider: Provider;
  model?: string;
}

export interface AgentBackend {
  readonly name: "current" | "langgraph";
  query(params: BackendQueryParams): AsyncGenerator<LoopEvent, void>;
}

export async function createBackend(): Promise<AgentBackend> {
  const flag = process.env.DOCKER_AGENT_BACKEND ?? "current";
  if (flag === "langgraph") {
    const { LangGraphBackend } = await import("./langgraph/LangGraphBackend");
    return new LangGraphBackend();
  }
  const { CurrentBackend } = await import("./CurrentBackend");
  return new CurrentBackend();
}
```

> Note: signature changed from sync to async. `QueryEngine.query()` must now `await createBackend()` — adjust Task 1.3 accordingly.

- [ ] **Step 5: Update QueryEngine to await the now-async factory**

In `src/QueryEngine.ts`, change:

```ts
const backend = createBackend();
const loopPromise = (async () => {
```

to:

```ts
const backendPromise = createBackend();
const loopPromise = (async () => {
  const backend = await backendPromise;
  try {
    for await (const ev of backend.query({ ... })) { ... }
  } ...
```

Move the inner generator consumption inside the `await backendPromise` block.

- [ ] **Step 6: Un-skip the langgraph factory test**

In `src/__tests__/backend/AgentBackendFactory.test.ts`, change `test.skip` back to `test`, and update each test to `await createBackend()`:

```ts
test("returns LangGraphBackend when DOCKER_AGENT_BACKEND=langgraph", async () => {
  const prev = process.env.DOCKER_AGENT_BACKEND;
  process.env.DOCKER_AGENT_BACKEND = "langgraph";
  const b = await createBackend();
  expect(b.name).toBe("langgraph");
  process.env.DOCKER_AGENT_BACKEND = prev;
});
```

(Update all three tests to be `async` and `await`.)

- [ ] **Step 7: Run the new smoke test**

Run: `pnpm vitest run src/backend/langgraph/LangGraphBackend.test.ts`
Expected: PASS.

- [ ] **Step 8: Run the factory test**

Run: `pnpm vitest run src/__tests__/backend/AgentBackendFactory.test.ts`
Expected: PASS (3 tests, no skips).

- [ ] **Step 9: Run the full suite — this is the parity gate**

Run: `pnpm test`
Expected: PASS for everything that does NOT set `DOCKER_AGENT_BACKEND=langgraph`. The default path still uses `CurrentBackend`. The langgraph smoke test passes with the new module.

- [ ] **Step 10: Commit**

```bash
git add src/backend/langgraph/LangGraphBackend.ts src/backend/langgraph/LangGraphBackend.test.ts src/backend/AgentBackend.ts src/QueryEngine.ts src/__tests__/backend/AgentBackendFactory.test.ts
git commit -m "feat(backend): LangGraphBackend behind feature flag (read-only parity)"
```

---

## Phase 3: Wrap remaining read-only tools + LangChain tool schema

### Task 3.1: Extend read-only allowlist to all safe tools

**Files:**
- Modify: `src/backend/langgraph/nodes/toolsNode.ts` (READ_ONLY_ALLOWLIST)

- [ ] **Step 1: Write a parity test asserting the event sequence for each read-only tool**

Create `src/backend/langgraph/toolsNode.parity.test.ts` — for each tool in `{validate_spec, resolve_dependency, check_port_conflict, list_stacks, inspect_drift, get_stack_status, get_health, get_logs}` drive a fake provider that emits exactly one tool call; assert at least `tool_call` + `tool_result` events are present and `output` is non-empty. Use the existing mock helpers. Use the SAME provider script as `tests/integration/plan-flow.test.ts` so behavior parity is byte-for-byte.

(One test per tool, 8 tests total. Each ~20 lines using the harness from Task 2.6.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm vitest run src/backend/langgraph/toolsNode.parity.test.ts`
Expected: FAIL — `validate_spec`, `resolve_dependency`, `check_port_conflict`, `get_health`, `get_logs` blocked by the allowlist.

- [ ] **Step 3: Expand the allowlist**

In `src/backend/langgraph/nodes/toolsNode.ts`:

```ts
const READ_ONLY_ALLOWLIST = new Set([
  "validate_spec",
  "resolve_dependency",
  "check_port_conflict",
  "list_stacks",
  "inspect_drift",
  "remediate_drift", // NOTE: moves to plan_review flow in Phase 4, gated inside node
  "get_stack_status",
  "get_health",
  "get_logs",
  "pull_image",       // gated requestPermission below
  "exec_docker",      // gated requestPermission below
]);
```

- [ ] **Step 4: Add permission gating in toolsNode (mirror query.ts:738-752)**

Append inside the `for (const tu of toolUses)` loop, before invoking the tool:

```ts
if (!READ_ONLY_ALLOWLIST.has(tu.name!)) { /* unchanged unsupported path */ }

const tool = findToolByName(getAgentTools(), tu.name!);
if (tool.needsPermission(parsed) && !ctx.allowSet.has(tool.name)) {
  // emit permission_request, await ctx.requestPermission — exactly the CurrentBackend contract
  emit({ type: "permission_request", id: tu.id!, tool: tu.name!, input: tu.input });
  const resp = await ctx.requestPermission(tu.name!, tu.input);
  if (resp.kind === "deny") {
    emit({ type: "tool_result", name: tu.name!, output: "User denied permission." });
    results.push({ toolUseId: tu.id!, name: tu.name!, input: tu.input, output: "User denied permission.", isError: false });
    continue;
  }
  if (resp.kind === "always_allow_in_session") ctx.allowSet.add(tool.name);
}
```

(`parsed` is obtained by running `tool.inputSchema.parse(tu.input)` before this check — see the existing `runTool` helper which already does this; lift the parse above the permission block.)

- [ ] **Step 5: Run parity test**

Run: `pnpm vitest run src/backend/langgraph/toolsNode.parity.test.ts`
Expected: PASS (8 tests).

- [ ] **Step 6: Run integration tests under the langgraph flag**

Run: `DOCKER_AGENT_BACKEND=langgraph pnpm vitest run tests/integration/plan-flow.test.ts`
Expected: this test directly constructs `QueryEngine` and the `QueryEngine` constructor's default backend is `current` unless env is read. Since we read env at factory call time, setting the env in the shell makes `QueryEngine` use `LangGraphBackend`. Expected: FAIL for path-related tests because `plan_stack` is still unsupported. We will fix this in Phase 4. For Phase 3 keep `plan-flow.test.ts` passing ONLY under `current` (the default), and add a `describe.skip` for the langgraph variant with a TODO note.

Capture the list of failing plan-related tests and document them in `src/backend.feature.md`.

- [ ] **Step 7: Commit**

```bash
git add src/backend/langgraph/nodes/toolsNode.ts src/backend/langgraph/toolsNode.parity.test.ts src/backend.feature.md
git commit -m "feat(langgraph): all read-only tools + permission gating parity"
```

---

### Task 3.2: Cross-backend parity suite

**Files:**
- Create: `src/__tests__/backend/CrossBackendParity.test.ts`

- [ ] **Step 1: Write a parameterized test that runs the same provider script under both backends**

```ts
import { describe, expect, test } from "vitest";
import type { ProviderEvent } from "src/services/api/types";
import type { LoopEvent } from "src/types/events";
// ... same mock setup as above ...

for (const backendName of ["current", "langgraph"] as const) {
  describe(`${backendName} backend parity`, () => {
    test("list_stacks emits identical LoopEvent types", async () => {
      process.env.DOCKER_AGENT_BACKEND = backendName;
      const { createBackend } = await import("src/backend/AgentBackend");
      const b = await createBackend();
      const got: string[] = [];
      for await (const ev of b.query({ /* same as smoke */ })) got.push(ev.type);
      expect(got).toContain("iteration_start");
      expect(got).toContain("tool_call");
      expect(got).toContain("tool_result");
      delete process.env.DOCKER_AGENT_BACKEND;
    });
  });
}
```

(Add 3-4 cases: empty user → end_turn, read-only tool call, permission denied, max_iterations.)

- [ ] **Step 2: Run**

Run: `pnpm vitest run src/__tests__/backend/CrossBackendParity.test.ts`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/__tests__/backend/CrossBackendParity.test.ts
git commit -m "test(backend): cross-backend parity harness"
```

---

## Phase 4: plan_stack interrupt + apply subgraph

### Task 4.1: plan_review node using interrupt()

**Files:**
- Create: `src/backend/langgraph/nodes/planReviewNode.ts`
- Modify: `src/backend/langgraph/graph.ts` (add node + conditional edge for plan_stack)
- Modify: `src/backend/langgraph/nodes/toolsNode.ts` (route `plan_stack` to `plan_review` instead of dispatching as a regular tool)

- [ ] **Step 1: Write the failing parity test — mirror tests/integration/plan-flow.test.ts**

Create `src/backend/langgraph/planReview.parity.test.ts`. Copy the cases from `tests/integration/plan-flow.test.ts` (approve, deny, blocked, rollback) verbatim but set `DOCKER_AGENT_BACKEND=langgraph` before constructing the `QueryEngine`. (The existing plan-flow tests stay green under `current`.)

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL — no plan_stack support yet.

- [ ] **Step 3: Implement planReviewNode**

Create `src/backend/langgraph/nodes/planReviewNode.ts`. Mirror `handlePlanStackToolUse` (src/query.ts:292+) including `PolicyEngine` gate, `planStack` blocking check, `requestConfirm` callback, and the `applyWithRollback` invocation. The node uses `interrupt()` from `@langchain/langgraph` to pause until the approval arrives; on resume it runs `applyWithRollback` and pushes its `LoopEvent` yields through `emit`.

Skeleton:

```ts
import { interrupt } from "@langchain/langgraph";
import { PolicyEngine } from "src/policy/PolicyEngine";
import { planStack } from "src/tools/planStack";
import { loadUserConfig } from "src/config";
import type { LoopContext } from "src/loopContext";
import type { LoopEvent } from "src/types/events";
import type { AgentState, PendingToolResult } from "../state";
import { formatPlanBlocker } from "src/query"; // EXPORT this fn from query.ts if not already
import { applyWithRollbackEquivalent } from "./applyWithRollbackNode"; // Task 4.2

export const planReviewNode = ({ ctx, emit }: { ctx: LoopContext; emit: (e: LoopEvent) => void }) =>
  async (state: typeof AgentState.State) => {
    const last = state.messages[state.messages.length - 1];
    const planCall = (last.content as Array<{ type: string; id?: string; input?: unknown }>)
      .find((b) => b.type === "tool_use" && b.name === "plan_stack");
    if (!planCall || !planCall.id) return {};
    // ... parse, PolicyEngine, planStack.exec, formatPlanBlocker — copy verbatim from query.ts:292-520 ...
    const plan = planStack.inputSchema.parse(planCall.input);
    // blocked path emits plan_ready? no — blocked returns error to LLM directly
    const result = /* call existing planStack logic */;
    if ("reason" in result) {
      const msg = formatPlanBlocker(result);
      emit({ type: "tool_result", name: "plan_stack", output: msg });
      return { messages: [{ role: "tool", toolUseId: planCall.id, content: msg, isError: true }] };
    }
    // success path: emit plan_ready via the ctx.requestConfirm callback (same contract as current)
    emit({
      type: "plan_ready",
      id: planCall.id,
      composeYaml: result.composeYaml,
      diff: result.diff,
      ...(result.autoGeneratedSecrets ? { autoGeneratedSecrets: result.autoGeneratedSecrets } : {}),
      ...(result.configFiles ? { configFiles: result.configFiles } : {}),
    });
    // interrupt() blocks until LangGraphBackend resumes the graph with { kind: "approve" | "deny" }
    const approval = interrupt("await_plan_approval");
    if (approval.kind === "deny") {
      return { messages: [{ role: "tool", toolUseId: planCall.id, content: "plan denied by user", isError: false }] };
    }
    // approved — run applyWithRollback as a sub-invoke that streams its own LoopEvents
    const applyResult = await applyWithRollbackEquivalent({
      stackName: result.stackName,
      desiredYaml: result.composeYaml,
      scaleOverrides: result.scaleOverrides,
      configFiles: result.configFiles ?? [],
      ctx,
      emit,
    });
    return {
      messages: [{ role: "tool", toolUseId: planCall.id, content: applyResult.resultMessage, isError: !applyResult.ok }],
    };
  };
```

(Detailed body transcribed literally from `src/query.ts:292-520` — every branch preserved: invalid spec, port conflict, missing env, user decline, approved apply with rollback. No behavioral shortcuts.)

- [ ] **Step 4: Implement applyWithRollbackEquivalent as a node helper**

Create `src/backend/langgraph/nodes/applyWithRollbackNode.ts` that exports `applyWithRollbackEquivalent`. It is the body of `applyWithRollback` (src/query.ts:143-239) verbatim, but instead of `yield* runTool(...)` it pushes through the `emit` callback — capture into the existing `runTool` adapter from `adapters/toolAdapter.ts`. It must preserve the `captureKnownGood` + `restore_previous`/`teardown_partial`/`none` three-way strategy exactly; `restoreConfigFiles` and `stateStore.appendHistory` are called at the same points.

- [ ] **Step 5: Route plan_stack to plan_review in graph**

In `src/backend/langgraph/graph.ts`, add a `plan_review` node and adjust the conditional edge from `agent`:

```ts
.addNode("plan_review", planReviewNode({ ctx: deps.ctx, emit: deps.emit }))
.addEdge("plan_review", "agent")          // always back to agent after tool message
// Conditional edge from agent:
.addConditionalEdges("agent", (state) => {
  const last = state.messages[state.messages.length - 1];
  const toolUses = (last?.content ?? []).filter((b) => b.type === "tool_use") as Array<{ name?: string }>;
  if (toolUses.length === 0) return END;
  if (state.iter >= 24) return END;
  if (toolUses.some((t) => t.name === "plan_stack")) return "plan_review";
  return "tools";
});
```

In `toolsNode.ts`, ensure `plan_stack` is NOT in the allowlist and emits a "routed to plan_review" no-op if hit — but the conditional routing above means it never reaches `toolsNode`.

- [ ] **Step 6: LangGraphBackend — support resume from approval**

In `LangGraphBackend.query()`, when the graph emits `plan_ready` (carrying `id`), the existing `QueryEngine.deferUserResponse` machinery (via `ctx.requestConfirm`) returns the answer. The node's `interrupt()` is then resumed by calling `graph.invoke(null, { command: { resume: approval } })` — see LangGraph JS [interrupts](https://docs.langchain.com/oss/javascript/langgraph/interrupts). Implement this by splitting the stream driver into a loop that detects `state.pendingApproval` and re-streams after resume.

(Concretely: use a `Command` object: `import { Command } from "@langchain/langgraph"; await graph.stream(new Command({ resume: approval }), config)`.)

- [ ] **Step 7: Run parity test**

Run: `DOCKER_AGENT_BACKEND=langgraph pnpm vitest run src/backend/langgraph/planReview.parity.test.ts`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/backend/langgraph/nodes/ src/backend/langgraph/graph.ts src/backend/langgraph/LangGraphBackend.ts src/backend/langgraph/planReview.parity.test.ts
git commit -m "feat(langgraph): plan_review node with interrupt() + applyWithRollback subflow"
```

---

### Task 4.2: typed_confirm flow for destroy_* and remediate_drift

**Files:**
- Modify: `src/backend/langgraph/nodes/toolsNode.ts`

- [ ] **Step 1: Mirror the typed_confirm gate from query.ts:575-652**

In `toolsNode`, when `tu.name === "destroy_all_stacks"` emit `typed_confirm_request` and `await ctx.requestTypedConfirm("DESTROY ALL", reason)`; if not matched, push a tool message identically to `CurrentBackend`. For `destroy_stack` with `removeVolumes` emit `typed_confirm_request` with phrase `DESTROY <stackName>`. For `remediate_drift` route to a `remediateDriftNode` that mirrors `handleRemediateDriftToolUse` (same shape as `planReviewNode` — uses `interrupt` for confirmation).

- [ ] **Step 2: Add parity tests copy**

Mirror the `destroy_all` / `destroy_stack --volumes` / `remediate_drift` cases from `tests/integration/plan-flow.test.ts` under `DOCKER_AGENT_BACKEND=langgraph`.

- [ ] **Step 3: Commit**

```bash
git add src/backend/langgraph/nodes/toolsNode.ts src/backend/langgraph/nodes/remediateDriftNode.ts src/backend/langgraph/typedConfirm.parity.test.ts
git commit -m "feat(langgraph): typed_confirm gate for destroy/remediate parity"
```

---

## Phase 5: Migrate mutating path and ship parity

### Task 5.1: Flip the default backend to `current`-parity verified, langgraph opt-in

**Files:**
- Modify: `src/backend.feature.md`
- Modify: `src/backend/AgentBackend.ts` (keep default = `current`; flip optional in a separate CLI flag from Phase 6 — out of scope here)

- [ ] **Step 1: Run the full plan-flow suite under both backends**

Run:
```bash
pnpm vitest run tests/integration/plan-flow.test.ts
DOCKER_AGENT_BACKEND=langgraph pnpm vitest run tests/integration/plan-flow.test.ts
```
Expected: both PASS with identical test counts.

- [ ] **Step 2: Run the cross-backend parity suite**

Run: `pnpm vitest run src/__tests__/backend/CrossBackendParity.test.ts`
Expected: PASS.

- [ ] **Step 3: Update feature doc**

In `src/backend.feature.md`, document the env var, the parity status, and the explicit warning that `langgraph` is opt-in:
- Both backends pass the same suite
- `current` remains default
- How to enable: `DOCKER_AGENT_BACKEND=langgraph docker-agent ...`

- [ ] **Step 4: Commit**

```bash
git add src/backend.feature.md
git commit -m "docs(backend): document langgraph opt-in and parity status"
```

---

### Task 5.2: Lint/typecheck/precheck gate

- [ ] **Step 1: Run precheck**

Run: `pnpm precheck`
Expected: PASS (typecheck + biome + vitest).

- [ ] **Step 2: Run smoke against the CLI**

Run a manual smoke (instructions only, no test code):
```bash
pnpm build
node ./dist/cli.js --help
node ./dist/cli.js        # enter REPL, type "list stacks" — should use CurrentBackend
DOCKER_AGENT_BACKEND=langgraph node ./dist/cli.js    # same REPL, "list stacks" via LangGraphBackend
```
Expected: identical UI output in both invocations.

- [ ] **Step 3: Commit if any whitespace/config fix was needed**

```bash
git add -u
git commit -m "chore: fix precheck findings after langgraph backend migration"
```

---

## Self-Review

**1. Spec coverage**
- "giữ CLI y hệt" → Tasks 1.3, 5.2: no command/UI change; backend injected under `QueryEngine`. ✓
- "không chạy LangGraph server" → LangGraph run in-process via `StateGraph`, no server. ✓
- "AgentBackend mới" → Task 1.1 interface, 1.2 DefaultBackend (CurrentBackend), 2.6 LangGraphBackend. ✓
- "Docker code hiện tại giữ" → `Tool`/`ToolContext`/`applyStack`/`planRollback` untouched; adapters call them. ✓
- "Human approval giữ — emit plan_ready" → Task 4.1 planReviewNode emits `plan_ready` with identical payload, `QueryEngine.deferUserResponse` unchanged. ✓
- "applyStack sau approval" → `applyWithRollbackEquivalent` only invoked after `interrupt()` resumes with approve. ✓
- "Không expose Docker shell" → no `shell()` tool used; `exec_docker` keeps its read-only whitelist. ✓
- "Spike first, không rewrite" → Phase 1 is pure shim; Phase 2 ties to read-only; Phase 4 only after parity tests. ✓
- Phase roadmap 1..5 → one task group per phase. ✓

**2. Placeholder scan**
- One `applyWithRollbackEquivalent` is described as "copy the body verbatim" — acceptable since the body is bounded (lines 143-239) and the source is referenced exactly. The engineer has a concrete reference. Keep.
- Task 4.1 step 3 has a `/* call existing planStack logic */` pseudomarker — but the task explicitly says "transcribed literally from src/query.ts:292-520". Acceptable given the boundary is explicit. No abstract "TBD".

**3. Type consistency**
- `AgentBackend.query` signature stable across all tasks
- `BackendQueryParams` keys (`messages`, `ctx`, `provider`, `model?`) match `QueryParams` from query.ts:29 ✓
- `LoopEvent` is the contract; backends emit it directly; `StreamedEvent`/`ToolRun`/`PendingToolResult` internal types defined in the tasks that first use them and reused unchanged ✓
- `createBackend` switches sync→async at 2.6; Task 2.6 Step 5 explicitly patches the call site at Task 1.3 ✓

No gaps found. Plan is implementation-ready.

---

## Execution Handoff

Plan complete and saved to `docs/plans/2026-06-26-langgraph-backend-migration.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for a 5-phase migration where each phase has a parity gate.

**2. Inline Execution** — Execute tasks in this session sequentially with checkpoints for review.

Which approach?