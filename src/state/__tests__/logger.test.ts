import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, test } from "vitest";
import { StructuredLogger } from "../logger";

describe("StructuredLogger", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "log-"));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  test("writes NDJSON lines to <sessionId>.ndjson", () => {
    const logger = new StructuredLogger(tmpDir, "sess-123");
    logger.log({
      ts: "2026-06-19T10:00:00.000Z",
      level: "info",
      sessionId: "sess-123",
      category: "turn_start",
      message: "user prompt received",
    });
    logger.close();

    const logPath = path.join(tmpDir, "sess-123.ndjson");
    const lines = fs.readFileSync(logPath, "utf-8").trim().split("\n");
    expect(lines.length).toBe(1);
    const line = lines[0];
    if (!line) throw new Error("expected one log line");
    const entry = JSON.parse(line);
    expect(entry.sessionId).toBe("sess-123");
    expect(entry.category).toBe("turn_start");
    expect(entry.message).toBe("user prompt received");
  });

  test("appends multiple entries as separate lines", () => {
    const logger = new StructuredLogger(tmpDir, "sess-456");
    logger.log({
      ts: "2026-06-19T10:00:00.000Z",
      level: "info",
      sessionId: "sess-456",
      category: "iteration_start",
      iteration: 1,
      message: "iteration 1",
    });
    logger.log({
      ts: "2026-06-19T10:00:01.000Z",
      level: "info",
      sessionId: "sess-456",
      category: "action",
      iteration: 1,
      message: "tool_call: plan_stack",
    });
    logger.close();

    const logPath = path.join(tmpDir, "sess-456.ndjson");
    const lines = fs.readFileSync(logPath, "utf-8").trim().split("\n");
    expect(lines.length).toBe(2);
  });

  test("redacts secret-looking values in data", () => {
    const logger = new StructuredLogger(tmpDir, "sess-789");
    logger.log({
      ts: "2026-06-19T10:00:00.000Z",
      level: "info",
      sessionId: "sess-789",
      category: "observation",
      message: "tool result",
      data: { POSTGRES_PASSWORD: "supersecret123", port: 5432 },
    });
    logger.close();

    const logPath = path.join(tmpDir, "sess-789.ndjson");
    const content = fs.readFileSync(logPath, "utf-8");
    expect(content).not.toContain("supersecret123");
    expect(content).toContain('"***"');
  });

  test("does not throw when log dir is unwritable (best-effort)", () => {
    const logger = new StructuredLogger("/nonexistent/path", "sess-err");
    expect(() =>
      logger.log({
        ts: "2026-06-19T10:00:00.000Z",
        level: "info",
        sessionId: "sess-err",
        category: "test",
        message: "no throw",
      }),
    ).not.toThrow();
    logger.close();
  });
});
