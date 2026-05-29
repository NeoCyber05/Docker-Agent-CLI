import { renderChatSession } from "src/main";
import { afterEach, describe, expect, test, vi } from "vitest";

describe("main interactive rendering", () => {
  const originalWrite = process.stdout.write.bind(process.stdout);

  afterEach(() => {
    process.stdout.write = originalWrite;
    vi.restoreAllMocks();
  });

  test("chat mode renders on the main terminal screen without clearing scrollback", async () => {
    const stdout: string[] = [];
    process.stdout.write = ((chunk: string | Uint8Array) => {
      stdout.push(typeof chunk === "string" ? chunk : new TextDecoder().decode(chunk));
      return true;
    }) as typeof process.stdout.write;
    const renderImpl = vi.fn(() => ({
      waitUntilExit: vi.fn(async () => undefined),
    }));

    await renderChatSession(
      {
        cwd: "D:/tmp",
        stateStore: {} as never,
        dockerEngine: {} as never,
        composeRunner: {} as never,
        provider: {
          name: "fake",
          stream: async function* () {},
        },
        providerName: "fake",
      },
      { renderImpl },
    );

    const output = stdout.join("");
    expect(renderImpl).toHaveBeenCalledTimes(1);
    expect(output).not.toContain("\u001B[?1049h");
    expect(output).not.toContain("\u001B[?1049l");
    expect(output).not.toContain("\u001B[2J");
  });
});
