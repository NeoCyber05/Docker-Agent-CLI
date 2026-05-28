import { parseArgs } from "src/main";
import { describe, expect, test } from "vitest";

describe("CLI argument parsing", () => {
  test("default chat command", () => {
    const r = parseArgs(["node", "docker-agent"]);
    expect(r.command).toBe("chat");
  });

  test("status [stack]", () => {
    const r = parseArgs(["node", "docker-agent", "status", "webapp"]);
    expect(r.command).toBe("status");
    expect(r.stack).toBe("webapp");
  });

  test("destroy <stack> --volumes --yes", () => {
    const r = parseArgs(["node", "docker-agent", "destroy", "webapp", "--volumes", "--yes"]);
    expect(r).toMatchObject({ command: "destroy", stack: "webapp", volumes: true, yes: true });
  });

  test("destroy --all", () => {
    const r = parseArgs(["node", "docker-agent", "destroy", "--all"]);
    expect(r).toMatchObject({ command: "destroy", all: true });
  });

  test("destroy --all --confirm 'DESTROY ALL'", () => {
    const r = parseArgs(["node", "docker-agent", "destroy", "--all", "--confirm", "DESTROY ALL"]);
    expect(r).toMatchObject({ command: "destroy", all: true, confirm: "DESTROY ALL" });
  });

  test("plan intent words", () => {
    const r = parseArgs(["node", "docker-agent", "plan", "nginx", "with", "tls"]);
    expect(r).toMatchObject({ command: "plan", intent: "nginx with tls" });
  });

  test("--provider flag captured", () => {
    const r = parseArgs(["node", "docker-agent", "--provider", "ollama"]);
    expect(r.providerFlag).toBe("ollama");
  });
});
