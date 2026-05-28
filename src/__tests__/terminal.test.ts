import { runInAlternateScreen } from "src/terminal";
import { describe, expect, test } from "vitest";

class FakeTerminal {
  chunks: string[] = [];

  constructor(public isTTY: boolean) {}

  write(chunk: string): boolean {
    this.chunks.push(chunk);
    return true;
  }
}

describe("terminal screen lifecycle", () => {
  test("wraps interactive TTY work in the alternate screen buffer", async () => {
    const terminal = new FakeTerminal(true);

    const result = await runInAlternateScreen(terminal, async () => {
      terminal.write("rendered");
      return 42;
    });

    expect(result).toBe(42);
    expect(terminal.chunks).toEqual([
      "\u001B[?1049h\u001B[2J\u001B[H",
      "rendered",
      "\u001B[?1049l",
    ]);
  });

  test("does not emit alternate-screen escapes for non-TTY output", async () => {
    const terminal = new FakeTerminal(false);

    await runInAlternateScreen(terminal, async () => {
      terminal.write("rendered");
    });

    expect(terminal.chunks).toEqual(["rendered"]);
  });
});
