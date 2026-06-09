/**
 * Bug 4 — Inline bold markdown: exploration test (EXPECTED TO FAIL on unfixed code)
 *
 * Property 4: Bug Condition — Render markdown bold, loại bỏ dấu `**`
 *
 * FOR ALL text WHERE isBugCondition_markdown(text) DO
 *   view := FormattedText(text)
 *   ASSERT rendersBoldSegments(view) AND NOT containsLiteralAsterisks(view)
 * END FOR
 *
 * THIS TEST IS EXPECTED TO FAIL ON UNFIXED CODE.
 * Failure confirms the bug exists: unfixed code prints literal `**` characters
 * instead of rendering bold text.
 *
 * DO NOT fix the test or the source code when this test fails.
 *
 * **Validates: Requirements 2.6**
 */

import { Readable, Writable } from "node:stream";
import { type Instance, render } from "ink";
import React from "react";
import { FormattedText } from "src/components/FormattedText";
import { afterEach, describe, expect, test } from "vitest";

// ---------------------------------------------------------------------------
// Test infrastructure (same pattern as PromptInput.test.ts)
// ---------------------------------------------------------------------------

class TestStdout extends Writable {
  columns = 120;
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
  setEncoding = () => this;
  setRawMode = () => this;

  _read() {}

  ref() {
    return this;
  }

  unref() {
    return this;
  }
}

/**
 * Strip ANSI escape codes from a string so we can inspect rendered text
 * without colour/style sequences in the way.
 */
function stripAnsi(value: string): string {
  // biome-ignore lint/suspicious/noControlCharactersInRegex: intentional ANSI strip
  return value.replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, "");
}

/**
 * Render <FormattedText text={text} /> and return the plain-text output.
 */
function renderFormattedText(text: string): { plainOutput: string; app: Instance } {
  const stdin = new TestStdin();
  const stdout = new TestStdout();
  const stderr = new TestStdout();

  const app = render(React.createElement(FormattedText, { text }), {
    stdin: stdin as unknown as NodeJS.ReadStream,
    stdout: stdout as unknown as NodeJS.WriteStream,
    stderr: stderr as unknown as NodeJS.WriteStream,
    debug: true,
    patchConsole: false,
    exitOnCtrlC: false,
  });

  const plainOutput = stripAnsi(stdout.output());
  return { plainOutput, app };
}

// ---------------------------------------------------------------------------
// Bug condition helpers
// ---------------------------------------------------------------------------

/** isBugCondition_markdown: text contains at least one **…** pair */
function isBugCondition_markdown(text: string): boolean {
  return /\*\*[^*]+\*\*/.test(text);
}

/**
 * containsLiteralAsterisks: rendered output contains literal `**` sequences.
 * On UNFIXED code this will be TRUE (the bug manifests).
 * After the fix this must be FALSE for any isBugCondition_markdown input.
 */
function containsLiteralAsterisks(view: string): boolean {
  return view.includes("**");
}

// ---------------------------------------------------------------------------
// Exploration tests — EXPECTED TO FAIL on unfixed code
// ---------------------------------------------------------------------------

describe("Bug 4 — Inline bold markdown: exploration (EXPECTED TO FAIL on unfixed code)", () => {
  const apps: Instance[] = [];

  afterEach(() => {
    for (const app of apps.splice(0)) {
      try {
        app.unmount();
        app.cleanup();
      } catch {
        // ignore cleanup errors
      }
    }
  });

  // -----------------------------------------------------------------------
  // Concrete case from spec: "**Cảnh báo**: xóa stack"
  // -----------------------------------------------------------------------
  test('Property 4 — concrete case: "**Cảnh báo**: xóa stack" must NOT contain literal ** — EXPECTED TO FAIL on unfixed code', async () => {
    const text = "**Cảnh báo**: xóa stack";

    // Confirm this input satisfies the bug condition
    expect(isBugCondition_markdown(text)).toBe(true);

    const { plainOutput, app } = renderFormattedText(text);
    apps.push(app);

    await new Promise<void>((resolve) => setImmediate(resolve));

    // The fixed code must NOT contain literal ** in the rendered output
    // On UNFIXED code: plainOutput contains "**Cảnh báo**" — test FAILS here
    expect(
      containsLiteralAsterisks(plainOutput),
      `Frame should NOT contain literal "**" but got:\n${plainOutput}`,
    ).toBe(false);
  });

  // -----------------------------------------------------------------------
  // Additional concrete cases from the spec
  // -----------------------------------------------------------------------
  test('Property 4 — concrete case: "**bold**" must NOT contain literal ** — EXPECTED TO FAIL on unfixed code', async () => {
    const text = "**bold**";

    expect(isBugCondition_markdown(text)).toBe(true);

    const { plainOutput, app } = renderFormattedText(text);
    apps.push(app);

    await new Promise<void>((resolve) => setImmediate(resolve));

    // On UNFIXED code: plainOutput contains "**bold**" — test FAILS here
    expect(
      containsLiteralAsterisks(plainOutput),
      `Frame should NOT contain literal "**" but got:\n${plainOutput}`,
    ).toBe(false);
  });

  test('Property 4 — concrete case: mixed "Hello **world** and **foo** here" — EXPECTED TO FAIL on unfixed code', async () => {
    const text = "Hello **world** and **foo** here";

    expect(isBugCondition_markdown(text)).toBe(true);

    const { plainOutput, app } = renderFormattedText(text);
    apps.push(app);

    await new Promise<void>((resolve) => setImmediate(resolve));

    // On UNFIXED code: plainOutput contains "**world**" and "**foo**" — test FAILS here
    expect(
      containsLiteralAsterisks(plainOutput),
      `Frame should NOT contain literal "**" but got:\n${plainOutput}`,
    ).toBe(false);
  });

  // -----------------------------------------------------------------------
  // Scoped PBT: for a representative sample of isBugCondition_markdown inputs
  // verify that rendered output never contains literal **
  // -----------------------------------------------------------------------
  test("Property 4 — PBT: representative bold-containing strings must NOT contain literal ** in rendered output — EXPECTED TO FAIL on unfixed code", async () => {
    // A hand-crafted representative sample of inputs satisfying isBugCondition_markdown
    const boldInputs = [
      "**Warning**",
      "**Error**: something went wrong",
      "Status: **running**",
      "**Cảnh báo**: xóa stack",
      "This is **important** text",
      "**A** and **B**",
      "prefix **middle** suffix",
    ];

    // Verify all sample inputs satisfy the bug condition
    for (const input of boldInputs) {
      expect(
        isBugCondition_markdown(input),
        `Input "${input}" should satisfy isBugCondition_markdown`,
      ).toBe(true);
    }

    const counterexamples: string[] = [];

    for (const text of boldInputs) {
      const { plainOutput, app } = renderFormattedText(text);
      apps.push(app);
      await new Promise<void>((resolve) => setImmediate(resolve));

      if (containsLiteralAsterisks(plainOutput)) {
        counterexamples.push(`"${text}" → rendered: "${plainOutput.trim()}"`);
      }
    }

    // On UNFIXED code: all inputs will appear in counterexamples — test FAILS here
    expect(
      counterexamples,
      `The following inputs rendered with literal "**" (bug confirmed):\n${counterexamples.join("\n")}`,
    ).toHaveLength(0);
  });
});
