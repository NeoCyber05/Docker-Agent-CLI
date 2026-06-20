import { describe, expect, test } from "vitest";
import { DB_PORT_MAP, checkDbPortExposure } from "../dbPortGuard";
import type { DraftServiceSpec } from "../specSchemas";

describe("DB_PORT_MAP", () => {
  test("covers postgres, mysql, mariadb, mongo, redis", () => {
    const labels = DB_PORT_MAP.map((e) => e.label).sort();
    expect(labels).toEqual(["mariadb", "mongo", "mysql", "postgres", "redis"]);
  });
});

describe("checkDbPortExposure", () => {
  test("blocks postgres 5432 published to host", () => {
    const issues = checkDbPortExposure({
      db: { image: "postgres:17-alpine", ports: ["5432:5432"] },
    });
    expect(issues.length).toBe(1);
    expect(issues[0]?.service).toBe("db");
    expect(issues[0]?.containerPort).toBe(5432);
  });

  test("allows postgres on a non-default host port mapping to 5432 container port", () => {
    expect(
      checkDbPortExposure({
        db: { image: "postgres:17-alpine", ports: ["15432:5432"] },
      }),
    ).toEqual([]);
  });

  test("allows postgres with no ports (internal only)", () => {
    expect(checkDbPortExposure({ db: { image: "postgres:17-alpine" } })).toEqual([]);
  });

  test("blocks mysql 3306 and redis 6379 simultaneously", () => {
    const issues = checkDbPortExposure({
      mysql: { image: "mysql:8", ports: ["3306:3306"] },
      cache: { image: "redis:7-alpine", ports: ["6379:6379"] },
    });
    expect(issues.length).toBe(2);
    expect(issues.map((i) => i.containerPort).sort()).toEqual([3306, 6379]);
  });

  test("ignores non-DB images", () => {
    expect(
      checkDbPortExposure({
        web: { image: "nginx:1.27-alpine", ports: ["80:80"] },
      }),
    ).toEqual([]);
  });
});
