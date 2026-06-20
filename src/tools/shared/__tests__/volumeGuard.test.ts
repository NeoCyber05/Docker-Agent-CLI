import { describe, expect, test } from "vitest";
import type { DraftServiceSpec } from "../specSchemas";
import { checkVolumeSafety } from "../volumeGuard";

function svc(volumes: string[]): DraftServiceSpec {
  return { image: "nginx:1.27-alpine", volumes };
}

describe("checkVolumeSafety", () => {
  test("passes for a named volume", () => {
    expect(checkVolumeSafety("/app", { web: svc(["data:/data"]) })).toEqual([]);
  });

  test("passes for a safe relative bind mount inside cwd", () => {
    expect(checkVolumeSafety("/app", { web: svc(["./config:/config:ro"]) })).toEqual([]);
  });

  test("blocks path traversal with .. that escapes cwd", () => {
    const issues = checkVolumeSafety("/app", { web: svc(["../../etc:/etc:ro"]) });
    expect(issues.length).toBe(1);
    expect(issues[0]?.code).toBe("path_traversal");
    expect(issues[0]?.volume).toBe("../../etc:/etc:ro");
  });

  test("blocks docker.sock bind mount", () => {
    const issues = checkVolumeSafety("/app", {
      web: svc(["/var/run/docker.sock:/var/run/docker.sock"]),
    });
    expect(issues.length).toBe(1);
    expect(issues[0]?.code).toBe("sensitive_host_path");
  });

  test("blocks /etc, /proc, /sys, /boot bind mounts", () => {
    const issues = checkVolumeSafety("/app", {
      a: svc(["/etc:/etc:ro"]),
      b: svc(["/proc:/proc:ro"]),
      c: svc(["/sys:/sys:ro"]),
      d: svc(["/boot:/boot:ro"]),
    });
    expect(issues.length).toBe(4);
    expect(issues.every((i) => i.code === "sensitive_host_path")).toBe(true);
  });

  test("blocks ~/.ssh bind mount", () => {
    const issues = checkVolumeSafety("/app", { web: svc(["~/.ssh:/root/.ssh:ro"]) });
    expect(issues.length).toBe(1);
    expect(issues[0]?.code).toBe("sensitive_host_path");
  });
});
