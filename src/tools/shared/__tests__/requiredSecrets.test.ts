import { describe, expect, test } from "vitest";
import { GENERIC_WEAK_VALUES, findRequiredSecrets, isWeakSecretValue } from "../requiredSecrets";

describe("findRequiredSecrets", () => {
  test("matches postgres image", () => {
    const rule = findRequiredSecrets("postgres:17-alpine");
    expect(rule?.required).toContain("POSTGRES_PASSWORD");
  });

  test("returns undefined for non-DB image", () => {
    expect(findRequiredSecrets("nginx:1.27-alpine")).toBeUndefined();
  });
});

function postgresRule() {
  const rule = findRequiredSecrets("postgres:17-alpine");
  if (!rule) throw new Error("expected postgres rule");
  return rule;
}

function mysqlRule() {
  const rule = findRequiredSecrets("mysql:8");
  if (!rule) throw new Error("expected mysql rule");
  return rule;
}

describe("isWeakSecretValue", () => {
  test("flags empty string", () => {
    expect(isWeakSecretValue("POSTGRES_PASSWORD", "", postgresRule())).toBe(true);
  });

  test("flags 'postgres' for POSTGRES_PASSWORD", () => {
    expect(isWeakSecretValue("POSTGRES_PASSWORD", "postgres", postgresRule())).toBe(true);
  });

  test("flags generic weak value 'password'", () => {
    expect(isWeakSecretValue("MYSQL_ROOT_PASSWORD", "password", mysqlRule())).toBe(true);
  });

  test("does not flag a strong random value", () => {
    expect(isWeakSecretValue("POSTGRES_PASSWORD", "xK9$mP2vQ7nR4wB8", postgresRule())).toBe(false);
  });

  test("GENERIC_WEAK_VALUES includes common defaults", () => {
    expect(GENERIC_WEAK_VALUES).toContain("password");
    expect(GENERIC_WEAK_VALUES).toContain("secret");
    expect(GENERIC_WEAK_VALUES).toContain("admin");
    expect(GENERIC_WEAK_VALUES).toContain("changeme");
  });
});
