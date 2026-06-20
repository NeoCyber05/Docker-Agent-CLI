import { describe, expect, test } from "vitest";
import { MAX_SERVICES_PER_STACK, checkResourceLimits } from "../resourceLimits";
import type { DraftServiceSpec } from "../specSchemas";

function svc(image = "nginx:1.27-alpine"): DraftServiceSpec {
  return { image };
}

describe("checkResourceLimits", () => {
  test("passes for a single service with no ports", () => {
    expect(checkResourceLimits({ web: svc() })).toEqual([]);
  });

  test("blocks when service count exceeds MAX_SERVICES_PER_STACK", () => {
    const services: Record<string, DraftServiceSpec> = {};
    for (let i = 0; i <= MAX_SERVICES_PER_STACK; i++) {
      services[`svc${i}`] = svc();
    }
    const issues = checkResourceLimits(services);
    expect(issues.length).toBe(1);
    expect(issues[0]?.code).toBe("too_many_services");
    expect(issues[0]?.message).toContain(String(MAX_SERVICES_PER_STACK + 1));
  });

  test("blocks port 0 and port 70000", () => {
    const issues = checkResourceLimits({
      a: { ...svc(), ports: ["0:80"] },
      b: { ...svc(), ports: ["70000:80"] },
    });
    expect(issues.map((i) => i.code)).toEqual(["invalid_port", "invalid_port"]);
    expect(issues[0]?.path).toBe("services.a.ports[0]");
  });

  test("warns on privileged host port below 1024", () => {
    const issues = checkResourceLimits({
      web: { ...svc(), ports: ["80:8080"] },
    });
    expect(issues.length).toBe(1);
    expect(issues[0]?.code).toBe("privileged_port");
    expect(issues[0]?.message).toContain("80");
  });

  test("passes for non-privileged port 8080", () => {
    expect(checkResourceLimits({ web: { ...svc(), ports: ["8080:80"] } })).toEqual([]);
  });

  test("ignores container-only ports (no host binding)", () => {
    expect(checkResourceLimits({ web: { ...svc(), ports: ["80"] } })).toEqual([]);
  });
});
