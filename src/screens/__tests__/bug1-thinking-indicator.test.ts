/**
 * Bug 1 — Thinking indicator: exploration test (EXPECTED TO FAIL on unfixed code)
 *
 * Property 1: Bug Condition — Thinking indicator có spinner động + elapsed timer
 * Validates: Requirements 2.1, 2.2
 *
 * Bug Condition:
 *   isBugCondition_thinking(S) = S.streaming === true AND S.pending === null
 *
 * Expected Behavior (after fix):
 *   hasAnimatedSpinner(view)  — spinner frame changes between captures
 *   showsElapsedTime(view)    — an elapsed "Ns" string appears in the frame
 *
 * EXPECTED OUTCOME ON UNFIXED CODE: FAIL
 *   The current implementation renders only the static string "Thinking..."
 *   with no spinner motion and no elapsed-seconds counter.
 *
 * Documented counterexamples (unfixed code):
 *   - frame1 === frame2 after advancing 200ms (frame unchanged after interval)
 *   - no match for /\d+s/ in either frame (no elapsed `s` string present)
 *
 * DO NOT fix this test or the implementation when it fails — the failure is the
 * signal that the bug exists. Re-run this test after implementing the fix in
 * task 6.1 to verify the bug is resolved.
 */

import { Readable, Writable } from "node:stream";
import { Box, type Instance, render } from "ink";
import React from "react";
import { ThinkingIndicator } from "src/components/ThinkingIndicator";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

// ---------------------------------------------------------------------------
// ThinkingState — wraps the fixed ThinkingIndicator in the same Box that
// REPL.tsx uses for the bug-condition render branch:
//
//   {!pending && streaming && (
//     <Box paddingLeft={1} marginY={1}>
//       <ThinkingIndicator />
//     </Box>
//   )}
//
// After the fix, ThinkingIndicator uses setInterval-driven state so that
// vi.advanceTimersByTime() causes the spinner to animate and the elapsed
// counter to appear.
// ---------------------------------------------------------------------------

function ThinkingState(): React.ReactElement {
  return React.createElement(
    Box,
    { paddingLeft: 1, marginY: 1 },
    React.createElement(ThinkingIndicator),
  );
}

// ---------------------------------------------------------------------------
// Test stream helpers (same pattern as existing tests)
// ---------------------------------------------------------------------------

class TestStdout extends Writable {
  columns = 100;
  rows = 24;
  isTTY = true;
  private chunks: string[] = [];

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

function stripAnsi(value: string): string {
  const pattern = new RegExp(`${String.fromCharCode(27)}\\[[0-9;?]*[ -/]*[@-~]`, "g");
  return value.replace(pattern, "");
}

// ---------------------------------------------------------------------------
// Bug-condition predicate (formalised from design.md)
// ---------------------------------------------------------------------------

/** isBugCondition_thinking(S): S.streaming === true AND S.pending === null */
function isBugConditionThinking(streaming: boolean, pending: unknown): boolean {
  return streaming === true && pending === null;
}

// ---------------------------------------------------------------------------
// Property helpers
// ---------------------------------------------------------------------------

/** Property: spinner frame changes between two captures (animated) */
function hasAnimatedSpinner(frame1: string, frame2: string): boolean {
  return frame1 !== frame2;
}

/** Property: an elapsed-time indicator in the form "Ns" (digits followed by 's') is present */
function showsElapsedTime(frame: string): boolean {
  return /\d+s/.test(frame);
}

// ---------------------------------------------------------------------------
// Helpers to flush Ink renders without blocking on fake-timer setImmediate
// ---------------------------------------------------------------------------

/** Flush pending microtasks and macro-tasks using real async scheduling */
async function flushAsync(): Promise<void> {
  // Two rounds of queueMicrotask + a real-time setImmediate equivalent via
  // Promise chaining ensures React state batching and Ink's render pipeline flush.
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

describe("Bug 1 — Thinking indicator: exploration (EXPECTED TO FAIL on unfixed code)", () => {
  const apps: Instance[] = [];

  beforeEach(() => {
    // Fake only timer APIs (setTimeout/setInterval) so that vi.advanceTimersByTime
    // controls interval-driven animations — but keep setImmediate/Promises real
    // so Ink's React render pipeline does not hang.
    vi.useFakeTimers({
      toFake: ["setTimeout", "setInterval", "clearTimeout", "clearInterval", "Date"],
    });
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    for (const app of apps.splice(0)) {
      try {
        app.unmount();
      } catch {
        /* ignore */
      }
      try {
        app.cleanup();
      } catch {
        /* ignore */
      }
    }
  });

  test("Property 1 — spinner frame changes AND elapsed 'Ns' appears in bug-condition state " +
    "(streaming=true, pending=null) — EXPECTED TO FAIL on unfixed code", async () => {
    // -------------------------------------------------------------------
    // Precondition: confirm we are asserting against the bug-condition state.
    // S = { streaming: true, pending: null } → isBugCondition_thinking is true.
    // -------------------------------------------------------------------
    expect(isBugConditionThinking(true, null)).toBe(true);

    // -------------------------------------------------------------------
    // Render ThinkingState — mirrors the REPL bug-condition branch exactly.
    // -------------------------------------------------------------------
    const stdin = new TestStdin();
    const stdout = new TestStdout();
    const stderr = new TestStdout();

    const app = render(React.createElement(ThinkingState), {
      stdin: stdin as unknown as NodeJS.ReadStream,
      stdout: stdout as unknown as NodeJS.WriteStream,
      stderr: stderr as unknown as NodeJS.WriteStream,
      debug: true,
      patchConsole: false,
      exitOnCtrlC: false,
    });
    apps.push(app);

    // Allow initial render to flush
    await flushAsync();

    // Capture frame 1 — the initial render of the thinking state
    const frame1 = stripAnsi(stdout.output());

    // Sanity: the thinking-state text is present in the initial frame
    expect(frame1).toContain("Thinking");

    // -------------------------------------------------------------------
    // Advance fake time by 200ms — sufficient for ≥2 spinner intervals
    // (~80–120ms each per design) and enough for a 1s elapsed counter tick.
    // On FIXED code the ThinkingIndicator uses setInterval; vi.advanceTimersByTime
    // fires those intervals synchronously, triggering React state updates.
    // On UNFIXED code there are no intervals — nothing changes.
    // -------------------------------------------------------------------
    vi.advanceTimersByTime(200);
    await flushAsync();

    // Capture frame 2 — should differ from frame1 on fixed code
    const frame2 = stripAnsi(stdout.output());

    // -------------------------------------------------------------------
    // ASSERTION 1 — hasAnimatedSpinner:
    //   The accumulated output must include a changed frame (spinner animated).
    //
    //   FAILS on unfixed code — counterexample:
    //     frame1 === frame2  (static "Thinking...", no state change at all)
    // -------------------------------------------------------------------
    expect(
      hasAnimatedSpinner(frame1, frame2),
      `Counterexample: frame unchanged after 200ms — spinner is static.\nframe1 === "${frame1.slice(0, 200)}"\nframe2 === "${frame2.slice(0, 200)}"`,
    ).toBe(true);

    // -------------------------------------------------------------------
    // ASSERTION 2 — showsElapsedTime:
    //   The frame must contain an elapsed-seconds indicator like "0s" or "1s".
    //
    //   FAILS on unfixed code — counterexample:
    //     no /\d+s/ match in frame2 (no elapsed timer rendered)
    // -------------------------------------------------------------------
    expect(
      showsElapsedTime(frame2),
      `Counterexample: no elapsed 's' string found.\nframe2 === "${frame2.slice(0, 200)}"`,
    ).toBe(true);
  }, 15_000); // generous timeout; the test should fail on assertion, not timeout
});
