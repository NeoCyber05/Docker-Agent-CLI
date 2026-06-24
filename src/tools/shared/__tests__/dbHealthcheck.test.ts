import { describe, expect, test } from "vitest";
import { injectDbHealthchecks } from "../dbHealthcheck";
import type { ServiceSpec } from "../../../types/stack";

describe("dbHealthcheck helper", () => {
  test("injects healthcheck to custom DB images when missing", () => {
    const services: Record<string, ServiceSpec> = {
      db: {
        image: "postgres:16-alpine",
      },
      web: {
        image: "nginx:1.27-alpine",
      },
    };

    const result = injectDbHealthchecks(services);

    expect(result.injectedCount).toBe(1);
    expect(services.db.healthcheck).toBeDefined();
    expect(services.db.healthcheck?.test).toEqual(["CMD-SHELL", "pg_isready -U \${POSTGRES_USER:-postgres}"]);
    expect(services.db.healthcheck?.start_period).toBe("30s");
    expect(services.web.healthcheck).toBeUndefined();
  });

  test("does not overwrite existing healthcheck", () => {
    const services: Record<string, ServiceSpec> = {
      db: {
        image: "mysql:8.4",
        healthcheck: {
          test: ["CMD", "mysqladmin", "ping"],
          interval: "5s",
          timeout: "2s",
          retries: 3,
        },
      },
    };

    const result = injectDbHealthchecks(services);

    expect(result.injectedCount).toBe(0);
    expect(services.db.healthcheck?.interval).toBe("5s");
    expect(services.db.healthcheck?.start_period).toBeUndefined();
  });

  test("upgrades array depends_on for DB dependencies", () => {
    const services: Record<string, ServiceSpec> = {
      db: {
        image: "mysql:8.0",
      },
      other: {
        image: "redis:7-alpine",
      },
      web: {
        image: "wordpress:latest",
        depends_on: ["db", "other"],
      },
    };

    const result = injectDbHealthchecks(services);

    expect(result.updatedDepsCount).toBe(1);
    expect(services.web.depends_on).toEqual({
      db: { condition: "service_healthy" },
      other: { condition: "service_healthy" }, // redis also matches DB pattern in DEFAULT_DB_HEALTHCHECKS
    });
  });

  test("upgrades array depends_on for DB dependencies while preserving non-DB dependencies", () => {
    const services: Record<string, ServiceSpec> = {
      db: {
        image: "postgres:16-alpine",
      },
      app: {
        image: "node:20-alpine",
      },
      web: {
        image: "nginx:alpine",
        depends_on: ["db", "app"],
      },
    };

    const result = injectDbHealthchecks(services);

    expect(result.updatedDepsCount).toBe(1);
    expect(services.web.depends_on).toEqual({
      db: { condition: "service_healthy" },
      app: { condition: "service_started" },
    });
  });

  test("upgrades record depends_on for DB dependencies without overwriting service_completed_successfully", () => {
    const services: Record<string, ServiceSpec> = {
      db: {
        image: "postgres:16-alpine",
      },
      migration: {
        image: "postgres:16-alpine",
      },
      web: {
        image: "nginx:alpine",
        depends_on: {
          db: { condition: "service_started" },
          migration: { condition: "service_completed_successfully" },
        },
      },
    };

    const result = injectDbHealthchecks(services);

    expect(result.updatedDepsCount).toBe(1);
    expect(services.web.depends_on).toEqual({
      db: { condition: "service_healthy" },
      migration: { condition: "service_completed_successfully" }, // preserved
    });
  });
});
