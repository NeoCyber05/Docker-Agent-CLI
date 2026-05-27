import { hashSecret, redactEnv, scrubLine, shouldRedact } from "src/state/secretRedactor";
import { describe, expect, test } from "vitest";

describe("secretRedactor", () => {
  test("shouldRedact catches common secret key patterns", () => {
    expect(shouldRedact("POSTGRES_PASSWORD")).toBe(true);
    expect(shouldRedact("API_KEY")).toBe(true);
    expect(shouldRedact("api-key")).toBe(true);
    expect(shouldRedact("SECRET_TOKEN")).toBe(true);
    expect(shouldRedact("DATABASE_URL")).toBe(false);
    expect(shouldRedact("NODE_ENV")).toBe(false);
  });

  test("shouldRedact avoids false positives on benign keys", () => {
    expect(shouldRedact("SECRETARY")).toBe(false);
    expect(shouldRedact("TOKENIZE")).toBe(false);
    expect(shouldRedact("AUTHENTIC")).toBe(false);
    expect(shouldRedact("PASSWORD_MANAGER")).toBe(false);
  });

  test("redactEnv splits into visible + secretKeys + hashes", () => {
    const result = redactEnv({ NODE_ENV: "prod", POSTGRES_PASSWORD: "hunter2" }, "webapp");
    expect(result.visible).toEqual({ NODE_ENV: "prod" });
    expect(result.secretKeys).toEqual(["POSTGRES_PASSWORD"]);
    expect(result.secretHashesByKey.POSTGRES_PASSWORD).toMatch(/^[a-f0-9]{64}$/);
  });

  test("identical values produce identical hashes per stack", () => {
    const r1 = redactEnv({ API_KEY: "v" }, "s");
    const r2 = redactEnv({ API_KEY: "v" }, "s");
    expect(r1.secretHashesByKey.API_KEY).toBe(r2.secretHashesByKey.API_KEY);
  });

  test("different stacks produce different hashes for same value", () => {
    const r1 = redactEnv({ API_KEY: "v" }, "stack1");
    const r2 = redactEnv({ API_KEY: "v" }, "stack2");
    expect(r1.secretHashesByKey.API_KEY).not.toBe(r2.secretHashesByKey.API_KEY);
  });

  test("hashSecret is deterministic HMAC-SHA-256 hex", () => {
    expect(hashSecret("hello", "salt")).toMatch(/^[a-f0-9]{64}$/);
  });

  describe("scrubLine", () => {
    test("replaces unquoted secret value", () => {
      expect(scrubLine("POSTGRES_PASSWORD=hunter2", new Set(["POSTGRES_PASSWORD"]))).toBe(
        "POSTGRES_PASSWORD=***",
      );
    });

    test("replaces double-quoted secret value", () => {
      expect(scrubLine('SECRET="my value"', new Set(["SECRET"]))).toBe("SECRET=***");
    });

    test("replaces single-quoted secret value", () => {
      expect(scrubLine("TOKEN='abc def'", new Set(["TOKEN"]))).toBe("TOKEN=***");
    });

    test("leaves line unchanged when key not in set", () => {
      expect(scrubLine("NODE_ENV=production", new Set(["SECRET"]))).toBe("NODE_ENV=production");
    });

    test("handles multiple keys on same line", () => {
      const line = "POSTGRES_PASSWORD=hunter2 API_KEY=abc";
      expect(scrubLine(line, new Set(["POSTGRES_PASSWORD", "API_KEY"]))).toBe(
        "POSTGRES_PASSWORD=*** API_KEY=***",
      );
    });
  });
});
