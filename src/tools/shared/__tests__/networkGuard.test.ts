import { describe, expect, test } from "vitest";
import { checkNetworkReferences } from "../networkGuard";
import type { DraftServiceSpec } from "../specSchemas";

function svc(networks: string[]): DraftServiceSpec {
  return { image: "nginx:1.27-alpine", networks };
}

describe("checkNetworkReferences", () => {
  test("passes when all service networks are declared", () => {
    expect(checkNetworkReferences({ web: svc(["frontend"]) }, { frontend: {} })).toEqual([]);
  });

  test("blocks undeclared network reference", () => {
    const issues = checkNetworkReferences({ web: svc(["ghost"]) }, { frontend: {} });
    expect(issues.length).toBe(1);
    expect(issues[0]?.code).toBe("undeclared_network");
    expect(issues[0]?.network).toBe("ghost");
  });

  test("passes when no top-level networks and service has no networks", () => {
    expect(checkNetworkReferences({ web: svc([]) }, undefined)).toEqual([]);
  });

  test("blocks multiple undeclared networks", () => {
    const issues = checkNetworkReferences({ web: svc(["frontend", "backend"]) }, { frontend: {} });
    expect(issues.length).toBe(1);
    expect(issues[0]?.network).toBe("backend");
  });

  test("passes when networks is undefined but services use default", () => {
    expect(checkNetworkReferences({ web: { image: "nginx:1.27-alpine" } }, undefined)).toEqual([]);
  });
});
