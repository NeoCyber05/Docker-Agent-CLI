import * as fs from "node:fs";
import * as path from "node:path";
import { shouldRedact } from "./secretRedactor";

export type LogLevel = "debug" | "info" | "warn" | "error";

export interface LogEntry {
  ts: string;
  level: LogLevel;
  sessionId: string;
  iteration?: number;
  category: string;
  message: string;
  data?: Record<string, unknown>;
}

export class StructuredLogger {
  private readonly logPath: string;
  private buffer: string[] = [];
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly maxBuffer = 50;
  private readonly flushDelayMs = 100;

  constructor(logDir: string, sessionId: string) {
    this.logPath = path.join(logDir, `${sessionId}.ndjson`);
  }

  log(entry: LogEntry): void {
    const redacted = this.redactEntry(entry);
    this.buffer.push(JSON.stringify(redacted));
    if (this.buffer.length >= this.maxBuffer) {
      this.flush();
    } else if (!this.flushTimer) {
      this.flushTimer = setTimeout(() => this.flush(), this.flushDelayMs);
    }
  }

  close(): void {
    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
    this.flush();
  }

  private flush(): void {
    if (this.buffer.length === 0) return;
    const chunk = `${this.buffer.join("\n")}\n`;
    this.buffer = [];
    try {
      fs.mkdirSync(path.dirname(this.logPath), { recursive: true });
      fs.appendFileSync(this.logPath, chunk, { encoding: "utf-8" });
    } catch {
      // Best-effort: log writes must never crash the agent loop.
    }
  }

  private redactEntry(entry: LogEntry): LogEntry {
    if (!entry.data) return entry;
    return { ...entry, data: redactObject(entry.data) };
  }
}

function redactObject(obj: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (shouldRedact(k)) {
      out[k] = "***";
    } else if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      out[k] = redactObject(v as Record<string, unknown>);
    } else {
      out[k] = v;
    }
  }
  return out;
}
