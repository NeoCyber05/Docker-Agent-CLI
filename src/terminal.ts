export interface TerminalWriter {
  isTTY?: boolean;
  write(chunk: string): boolean;
}

const ENTER_ALTERNATE_SCREEN = "\u001B[?1049h";
const EXIT_ALTERNATE_SCREEN = "\u001B[?1049l";
const CLEAR_VIEWPORT = "\u001B[2J\u001B[H";

export async function runInAlternateScreen<T>(
  terminal: TerminalWriter,
  run: () => Promise<T>,
): Promise<T> {
  if (!terminal.isTTY) {
    return await run();
  }

  terminal.write(ENTER_ALTERNATE_SCREEN + CLEAR_VIEWPORT);
  try {
    return await run();
  } finally {
    terminal.write(EXIT_ALTERNATE_SCREEN);
  }
}
