import { describe, expect, test } from "vitest";
import { MockComposeRunner } from "../mockComposeRunner";

describe("MockComposeRunner", () => {
  test("forStack returns a bound runner that records its identity", () => {
    const runner = new MockComposeRunner("/cwd");
    const bound = runner.forStack("webapp", "/tmp/webapp.yaml");
    expect(runner.forStackCalls).toEqual([
      { stackName: "webapp", yamlPath: "/tmp/webapp.yaml" },
    ]);
    expect(bound.spawnedArgs).toEqual([
      "compose",
      "-p",
      "webapp",
      "--project-directory",
      "/cwd",
      "-f",
      "/tmp/webapp.yaml",
    ]);
  });

  test("up records its options and yields a fake stdout line", async () => {
    const runner = new MockComposeRunner("/c");
    const bound = runner.forStack("a", "/a.yaml");
    const out: string[] = [];
    let exit = -1;
    for await (const line of bound.up({ detach: true })) out.push(line);
    exit = bound.lastExitCode;
    expect(bound.upCalls).toEqual([{ detach: true }]);
    expect(out.join("")).toContain("a");
    expect(exit).toBe(0);
  });

  test("boundFor returns the same instance per stackName", () => {
    const runner = new MockComposeRunner("/c");
    const b1 = runner.forStack("x", "/x.yaml");
    const b2 = runner.boundFor("x");
    expect(b1).toBe(b2);
  });

  test("forStack uses cwd from constructor", () => {
    const runner = new MockComposeRunner("/project");
    const bound = runner.forStack("svc", "/project/.docker-agent/stacks/svc.yaml");
    expect(bound.cwd).toBe("/project");
    expect(bound.spawnedArgs).toContain("/project");
  });
});