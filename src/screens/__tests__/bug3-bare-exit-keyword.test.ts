/**
 * Bug 3 — Bare exit/quit keyword: exploration test (EXPECTED TO FAIL on unfixed code)
 *
 * Property 3: Bug Condition — Thoát REPL khi nhập exit/quit trần
 * Validates: Requirements 2.5
 *
 * Bug Condition:
 *   isBugCondition_exit(input) = toLowerCase(trim(input)) === "exit" OR === "quit"
 *
 * Expected Behavior (after fix):
 *   effect === EXIT_REPL  — the Ink exit() function is called
 *   NOT calledLLM(input)  — engine.query() is NOT called
 *
 * EXPECTED OUTCOME ON UNFIXED CODE: FAIL
 *   The current handleSubmit only routes slash commands (/exit, /quit).
 *   Bare "exit" / "quit" fall through to engine.query() just like any other prompt.
 *
 * Documented counterexamples (unfixed code):
 *   - engine.query("exit") is called instead of exit()
 *   - engine.query("quit") is called instead of exit()
 *   - engine.query("  QUIT  ") (trimmed: "quit") is called instead of exit()
 *   - engine.query("EXIT") (lowered: "exit") is called instead of exit()
 *   - app.waitUntilExit() never resolves (REPL stays alive)
 *
 * DO NOT fix this test or the implementation when it fails — the failure is the
 * signal that the bug exists. Re-run this test after implementing the fix in
 * task 6.3 to verify the bug is resolved.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { Readable, Writable } from "node:stream";
import { type Instance, render } from "ink";
import React from "react";
import { QueryEngine } from "src/QueryEngine";
import { REPL } from "src/screens/REPL";
import { MemoryApiKeyStore } from "src/secrets/apiKeyStore";
import { StateStore } from "src/state/StateStore";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { MockComposeRunner } from "../../../tests/mocks/mockComposeRunner";
import { MockDockerEngine } from "../../../tests/mocks/mockDockerEngine";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

class TestStdout extends Writable {
  columns: number;
  rows: number;
  isTTY = true;
  private chunks: string[] = [];

  constructor({ columns, rows }: { columns: number; rows: number }) {
    super();
    this.columns = columns;
    this.rows = rows;
  }

  _write(chunk: Buffer | string, _encoding: BufferEncoding, callback: (error?: Error) => void) {
    this.chunks.push(String(chunk));
    callback();
  }

  output(): string {
    return this.chunks.join("");
  }
}

class TestStdin extends Readable {
  isTTY = true;
  setEncoding = vi.fn();
  setRawMode = vi.fn();

  _read() {}

  ref() {
    return this;
  }

  unref() {
    return this;
  }
}

/** A provider that never yields — safe for tests that should never reach engine.query */
function neverProvider() {
  return {
    name: "fake",
    stream: async function* () {
      // should not be called for exit/quit inputs
      yield { type: "text" as const, text: "unexpected-llm-call" };
    },
  };
}

// ---------------------------------------------------------------------------
// Bug Condition helper (formalised in design.md)
// ---------------------------------------------------------------------------

/** isBugCondition_exit(input): trim().toLowerCase() === "exit" OR "quit" */
function isBugConditionExit(input: string): boolean {
  const t = input.trim().toLowerCase();
  return t === "exit" || t === "quit";
}

// ---------------------------------------------------------------------------
// Test factory — renders REPL, submits one line, waits for exit or timeout
// ---------------------------------------------------------------------------

async function submitAndCheckExit(
  input: string,
  querySpy: {
    mockImplementation: (fn: (...args: unknown[]) => unknown) => void;
  },
): Promise<{ exited: boolean; queryCalledWith: string[] }> {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "bug3-exit-"));

  const stdout = new TestStdout({ columns: 100, rows: 24 });
  const stderr = new TestStdout({ columns: 100, rows: 24 });
  const stdin = new TestStdin();

  const app = render(
    React.createElement(REPL, {
      version: "0.1.0",
      deps: {
        cwd: tmp,
        stateStore: new StateStore(tmp),
        dockerEngine: new MockDockerEngine() as never,
        composeRunner: new MockComposeRunner(tmp) as never,
        provider: neverProvider() as never,
        providerName: "fake",
        apiKeyStore: new MemoryApiKeyStore(),
      },
    }),
    {
      stdout: stdout as unknown as NodeJS.WriteStream,
      stderr: stderr as unknown as NodeJS.WriteStream,
      stdin: stdin as unknown as NodeJS.ReadStream,
      debug: true,
      patchConsole: false,
      exitOnCtrlC: false,
    },
  );

  // Wait for initial render
  await new Promise((resolve) => setImmediate(resolve));

  // Track which prompts were forwarded to engine.query
  const queryCalledWith: string[] = [];
  querySpy.mockImplementation(async function* (...args: unknown[]) {
    queryCalledWith.push(args[0] as string);
    yield { type: "message_stop" as const, stopReason: "end_turn" as const };
  });

  // Submit the input line
  stdin.push(input);
  stdin.emit("readable");
  await new Promise((resolve) => setImmediate(resolve));
  stdin.push("\r");
  stdin.emit("readable");
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  // Give the REPL up to 300ms to exit (for fixed code) — unfixed code won't exit
  const exitRace = await Promise.race([
    app.waitUntilExit().then(() => true),
    new Promise<false>((resolve) => setTimeout(() => resolve(false), 300)),
  ]);

  try {
    app.unmount();
    app.cleanup();
  } catch {
    // ignore cleanup errors
  }
  fs.rmSync(tmp, { recursive: true, force: true });

  return { exited: exitRace === true, queryCalledWith };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Bug 3 — Bare exit/quit keyword: exploration (EXPECTED TO FAIL on unfixed code)", () => {
  let querySpy: {
    mockImplementation: (fn: (...args: unknown[]) => unknown) => void;
  };

  beforeEach(() => {
    // Spy on QueryEngine.prototype.query so we can detect if LLM was called
    querySpy = vi.spyOn(QueryEngine.prototype, "query") as unknown as typeof querySpy;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // -------------------------------------------------------------------------
  // Concrete bug-condition inputs (isBugConditionExit === true for each)
  // -------------------------------------------------------------------------

  const bugConditionCases: Array<{ label: string; input: string }> = [
    { label: '"exit"', input: "exit" },
    { label: '"quit"', input: "quit" },
    { label: '"  QUIT  " (whitespace + uppercase)', input: "  QUIT  " },
    { label: '"EXIT" (uppercase)', input: "EXIT" },
  ];

  for (const { label, input } of bugConditionCases) {
    test(`Property 3 — submitting ${label} MUST call exit() and NOT call engine.query — EXPECTED TO FAIL on unfixed code`, async () => {
      // Confirm precondition: input satisfies bug condition
      expect(isBugConditionExit(input)).toBe(true);

      const { exited, queryCalledWith } = await submitAndCheckExit(input, querySpy);

      // ASSERTION 1: REPL must have exited (exit() was called via Ink useApp)
      // FAILS on unfixed code — REPL stays alive, exited === false
      expect(exited).toBe(true);

      // ASSERTION 2: engine.query must NOT have been called with the exit keyword
      // FAILS on unfixed code — engine.query("exit") / engine.query("quit") IS called
      expect(queryCalledWith).toHaveLength(0);
    });
  }

  // -------------------------------------------------------------------------
  // Boundary / preservation: sentences that CONTAIN "exit"/"quit" but are NOT
  // the bare keyword — these MUST NOT trigger exit (REQ 3.5)
  // -------------------------------------------------------------------------

  const preservationCases: Array<{ label: string; input: string }> = [
    { label: '"how do I exit a container"', input: "how do I exit a container" },
    { label: '"please quit and restart"', input: "please quit and restart" },
    { label: '"exiting now"', input: "exiting now" },
  ];

  for (const { label, input } of preservationCases) {
    test(`Preservation REQ 3.5 — submitting ${label} must NOT exit and MUST go to engine.query`, async () => {
      // Confirm precondition: input does NOT satisfy bug condition
      expect(isBugConditionExit(input)).toBe(false);

      const { exited, queryCalledWith } = await submitAndCheckExit(input, querySpy);

      // Must NOT exit
      expect(exited).toBe(false);

      // Must have forwarded the prompt to LLM
      expect(queryCalledWith.length).toBeGreaterThan(0);
    });
  }
});
