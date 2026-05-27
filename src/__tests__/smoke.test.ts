import { main } from "src/main";
import { describe, expect, test } from "vitest";

describe("main entrypoint", () => {
  test("--version exits with code 0 and prints the package version", async () => {
    const stdout: string[] = [];
    const origWrite = process.stdout.write.bind(process.stdout);
    process.stdout.write = ((chunk: string | Uint8Array) => {
      stdout.push(typeof chunk === "string" ? chunk : new TextDecoder().decode(chunk));
      return true;
    }) as typeof process.stdout.write;
    let exitCode = -1;
    try {
      exitCode = await main(["node", "docker-agent", "--version"]);
    } finally {
      process.stdout.write = origWrite;
    }
    expect(exitCode).toBe(0);
    expect(stdout.join("")).toMatch(/0\.1\.0/);
  });
});
