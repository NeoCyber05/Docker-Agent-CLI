import { execDocker } from "src/tools/execDocker";
import { describe, expect, test } from "vitest";

describe("exec_docker whitelist", () => {
  test("allowed subcommand passes validation", () => {
    expect(() => execDocker.inputSchema.parse({ args: ["ps", "--all"] })).not.toThrow();
  });

  test("rejected subcommands fail validation", () => {
    expect(() => execDocker.inputSchema.parse({ args: ["rm", "-f", "abc"] })).toThrow();
    expect(() => execDocker.inputSchema.parse({ args: ["exec", "x", "sh"] })).toThrow();
    expect(() => execDocker.inputSchema.parse({ args: ["prune"] })).toThrow();
    expect(() => execDocker.inputSchema.parse({ args: ["kill", "x"] })).toThrow();
  });
});
