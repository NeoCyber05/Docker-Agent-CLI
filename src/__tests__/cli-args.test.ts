import { parseArgs } from "src/main";
import { describe, expect, test } from "vitest";

describe("CLI argument parsing", () => {
  test("default parses empty args", () => {
    const r = parseArgs(["node", "docker-agent"]);
    expect(r).toEqual({});
  });

  test("--provider flag captured", () => {
    const r = parseArgs(["node", "docker-agent", "--provider", "ollama"]);
    expect(r.providerFlag).toBe("ollama");
  });

  test("--model flag captured", () => {
    const r = parseArgs(["node", "docker-agent", "--model", "gpt-4o"]);
    expect(r.model).toBe("gpt-4o");
  });

  test("-y flag captured", () => {
    const r = parseArgs(["node", "docker-agent", "-y"]);
    expect(r.yes).toBe(true);
  });

  test("--resume flag captured as true if no value", () => {
    const r = parseArgs(["node", "docker-agent", "--resume"]);
    expect(r.resume).toBe(true);
  });

  test("--resume flag captured as string if value provided", () => {
    const r = parseArgs(["node", "docker-agent", "--resume", "12345"]);
    expect(r.resume).toBe("12345");
  });
});
