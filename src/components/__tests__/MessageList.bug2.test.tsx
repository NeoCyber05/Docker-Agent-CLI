/**
 * Bug 2 Exploration Test — Assistant message label/colour
 *
 * **Validates: Requirements 2.3, 2.4**
 *
 * Property 2 (Bug Condition):
 *   For any UIMessage M where isBugCondition_role(M) is true (M.role === "assistant"),
 *   renderMessage(M) SHALL display a distinct label/prefix AND/OR a distinct colour
 *   to visually differentiate the assistant message from user messages.
 *
 * EXPECTED OUTCOME on UNFIXED code: FAIL
 *   The unfixed MessageList renders assistant messages via bare <FormattedText> with
 *   no label, no prefix, and no colour — hasDistinctLabelOrColor returns false.
 *
 * Do NOT fix the source code or this test when it fails. The failure documents the
 * counterexample that proves the bug exists. This same test will pass after the fix.
 */

import { Readable, Writable } from "node:stream";
import { type Instance, render } from "ink";
import React from "react";
import { MessageList, type UIMessage } from "src/components/MessageList";
import { afterEach, describe, expect, test } from "vitest";

// ---------------------------------------------------------------------------
// Minimal stream stubs (same pattern as PromptInput.test.ts)
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

function stripAnsi(value: string): string {
  // Strips ANSI escape sequences so we can check visible text
  const pattern = new RegExp(`${String.fromCharCode(27)}\\[[0-9;?]*[ -/]*[@-~]`, "g");
  return value.replace(pattern, "");
}

/**
 * Renders a MessageList with the given messages and returns the stripped text output.
 */
function renderMessageList(messages: UIMessage[]): {
  text: string;
  rawOutput: string;
  app: Instance;
} {
  const stdin = new TestStdin();
  const stdout = new TestStdout();
  const stderr = new TestStdout();

  const app = render(React.createElement(MessageList, { messages }), {
    stdin: stdin as unknown as NodeJS.ReadStream,
    stdout: stdout as unknown as NodeJS.WriteStream,
    stderr: stderr as unknown as NodeJS.WriteStream,
    debug: true,
    patchConsole: false,
    exitOnCtrlC: false,
  });

  const rawOutput = stdout.output();
  const text = stripAnsi(rawOutput);
  return { text, rawOutput, app };
}

// ---------------------------------------------------------------------------
// Helper — hasDistinctLabelOrColor
//
// Checks whether the rendered output for an assistant message contains:
//   (a) a distinct label/prefix such as "Agent" or "Assistant", OR
//   (b) a magenta/purple ANSI colour code (common choice for agent label)
//
// On UNFIXED code neither condition is true, so this returns false.
// ---------------------------------------------------------------------------

const ASSISTANT_LABEL_PATTERNS = [/\bAgent\b/i, /\bAssistant\b/i];
// ANSI magenta foreground codes: ESC[35m or ESC[95m (bright magenta)
// biome-ignore lint/suspicious/noControlCharactersInRegex: ESC char (\x1b) is intentional for ANSI code detection
const MAGENTA_ANSI = /\x1b\[(?:35|95|1;35|1;95)m/;

function hasDistinctLabelOrColor(rawOutput: string, strippedText: string): boolean {
  const hasLabel = ASSISTANT_LABEL_PATTERNS.some((re) => re.test(strippedText));
  const hasMagenta = MAGENTA_ANSI.test(rawOutput);
  return hasLabel || hasMagenta;
}

// ---------------------------------------------------------------------------
// isBugCondition_role — formalised from design.md
// ---------------------------------------------------------------------------

function isBugCondition_role(m: UIMessage): boolean {
  return m.role === "assistant";
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Bug 2 — Assistant message label/colour (exploration, expected to FAIL on unfixed code)", () => {
  const apps: Instance[] = [];

  afterEach(() => {
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

  test("Property 2: assistant message has a distinct label or colour (isBugCondition_role true)", async () => {
    // Bug condition: M.role === "assistant"
    const message: UIMessage = {
      key: 1,
      role: "assistant",
      text: "Đã tạo plan cho nginx stack.",
    };

    expect(isBugCondition_role(message)).toBe(true);

    const { text, rawOutput, app } = renderMessageList([message]);
    apps.push(app);

    // Give Ink one tick to flush output
    await new Promise<void>((resolve) => setImmediate(resolve));

    // The rendered frame must contain the assistant text (sanity check)
    expect(text).toContain("Đã tạo plan cho nginx stack.");

    // Property 2 assertion:
    //   UNFIXED code: this FAILS — no label "Agent"/distinct colour in output
    //   FIXED code: this PASSES — label/colour present
    expect(hasDistinctLabelOrColor(rawOutput, text)).toBe(true);
  });

  test("Property 2: assistant message with arbitrary text still shows label/colour", async () => {
    const texts = ["Hello!", "**Cảnh báo**: xóa stack", "", "Multiple\nlines\nof text"];

    for (const msgText of texts) {
      const message: UIMessage = { key: 2, role: "assistant", text: msgText };
      expect(isBugCondition_role(message)).toBe(true);

      const { text, rawOutput, app } = renderMessageList([message]);
      apps.push(app);
      await new Promise<void>((resolve) => setImmediate(resolve));

      // Property 2: every assistant message must have a distinct label or colour
      // EXPECTED TO FAIL on unfixed code — no label/colour rendered
      expect(
        hasDistinctLabelOrColor(rawOutput, text),
        `Expected distinct label/colour for assistant message with text: "${msgText}" — got: "${text}"`,
      ).toBe(true);
    }
  });

  test("sanity: user message renders with ▶ prefix (non-bug-condition, baseline)", async () => {
    const message: UIMessage = { key: 3, role: "user", text: "Deploy nginx" };
    expect(isBugCondition_role(message)).toBe(false);

    const { text, app } = renderMessageList([message]);
    apps.push(app);
    await new Promise<void>((resolve) => setImmediate(resolve));

    // User message already has ▶ prefix — this should pass even on unfixed code
    expect(text).toContain("▶");
    expect(text).toContain("Deploy nginx");
  });
});
