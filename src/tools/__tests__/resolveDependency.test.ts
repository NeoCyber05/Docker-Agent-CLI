import { resolveDependencies } from "src/tools/resolveDependency";
import { describe, expect, test } from "vitest";

describe("resolve_dependency", () => {
  test("orders dependencies before dependents", () => {
    const result = resolveDependencies({
      api: { image: "example/api:1", depends_on: ["db"] },
      db: { image: "postgres:16-alpine" },
    });
    expect(result).toEqual({ valid: true, order: ["db", "api"], missing: [], cycles: [] });
  });

  test("reports missing dependency names", () => {
    expect(
      resolveDependencies({ api: { image: "example/api:1", depends_on: ["db"] } }),
    ).toMatchObject({
      valid: false,
      missing: [{ service: "api", dependency: "db" }],
    });
  });

  test("reports a dependency cycle", () => {
    expect(
      resolveDependencies({
        api: { image: "example/api:1", depends_on: ["worker"] },
        worker: { image: "example/worker:1", depends_on: ["api"] },
      }),
    ).toMatchObject({ valid: false, cycles: [["api", "worker", "api"]] });
  });

  test("supports object-form depends_on", () => {
    const result = resolveDependencies({
      api: { image: "example/api:1", depends_on: { db: { condition: "service_started" } } },
      db: { image: "postgres:16-alpine" },
    });
    expect(result).toMatchObject({ valid: true, order: ["db", "api"] });
  });
});
