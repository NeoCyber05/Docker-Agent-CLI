import type { ServiceSpec } from "../../types/stack";

export interface DefaultHealthcheck {
  imagePattern: RegExp;
  healthcheck: {
    test: string | string[];
    interval: string;
    timeout: string;
    retries: number;
    start_period: string;
  };
}

export const DEFAULT_DB_HEALTHCHECKS: DefaultHealthcheck[] = [
  {
    imagePattern: /^postgres(:|$)/,
    healthcheck: {
      test: ["CMD-SHELL", "pg_isready -U \${POSTGRES_USER:-postgres}"],
      interval: "10s",
      timeout: "5s",
      retries: 5,
      start_period: "30s",
    },
  },
  {
    imagePattern: /^mysql(:|$)/,
    healthcheck: {
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"],
      interval: "10s",
      timeout: "5s",
      retries: 5,
      start_period: "30s",
    },
  },
  {
    imagePattern: /^mariadb(:|$)/,
    healthcheck: {
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"],
      interval: "10s",
      timeout: "5s",
      retries: 5,
      start_period: "30s",
    },
  },
  {
    imagePattern: /^mongo(:|$)/,
    healthcheck: {
      test: ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"],
      interval: "10s",
      timeout: "5s",
      retries: 5,
      start_period: "30s",
    },
  },
  {
    imagePattern: /^redis(:|$)/,
    healthcheck: {
      test: ["CMD", "redis-cli", "ping"],
      interval: "10s",
      timeout: "3s",
      retries: 5,
      start_period: "5s",
    },
  },
];

/**
 * Auto-injects default healthchecks for databases in the planned stack services
 * and updates dependent services' depends_on conditions to service_healthy.
 */
export function injectDbHealthchecks(services: Record<string, ServiceSpec>): {
  injectedCount: number;
  updatedDepsCount: number;
} {
  let injectedCount = 0;
  let updatedDepsCount = 0;

  const dbServices = new Set<string>();

  // 1. Inject healthchecks for DBs (both catalog and custom images)
  for (const [name, spec] of Object.entries(services)) {
    const rule = DEFAULT_DB_HEALTHCHECKS.find((r) => r.imagePattern.test(spec.image));
    if (rule) {
      dbServices.add(name);
      if (!spec.healthcheck) {
        spec.healthcheck = { ...rule.healthcheck };
        injectedCount++;
      }
    }
  }

  // 2. Update depends_on for services that depend on the injected DB services
  for (const [name, spec] of Object.entries(services)) {
    if (!spec.depends_on) continue;

    if (Array.isArray(spec.depends_on)) {
      // Convert array depends_on to record with service_healthy condition for DB services
      const newDependsOn: Record<
        string,
        { condition: "service_started" | "service_healthy" | "service_completed_successfully" }
      > = {};
      let changed = false;

      for (const dep of spec.depends_on) {
        if (dbServices.has(dep)) {
          newDependsOn[dep] = { condition: "service_healthy" };
          changed = true;
        } else {
          newDependsOn[dep] = { condition: "service_started" };
        }
      }

      if (changed) {
        spec.depends_on = newDependsOn;
        updatedDepsCount++;
      }
    } else if (typeof spec.depends_on === "object") {
      // Check if any DB service is in the record and doesn't already demand service_healthy
      let changed = false;
      const newDependsOn = { ...spec.depends_on };

      for (const dep of Object.keys(newDependsOn)) {
        if (dbServices.has(dep)) {
          const currentDep = newDependsOn[dep];
          // Do NOT override service_completed_successfully or other explicit conditions
          if (
            currentDep &&
            currentDep.condition !== "service_healthy" &&
            currentDep.condition !== "service_completed_successfully"
          ) {
            newDependsOn[dep] = { ...currentDep, condition: "service_healthy" };
            changed = true;
          }
        }
      }

      if (changed) {
        spec.depends_on = newDependsOn;
        updatedDepsCount++;
      }
    }
  }

  return { injectedCount, updatedDepsCount };
}
