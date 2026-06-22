import * as fs from "node:fs";
import * as path from "node:path";
import type { Message } from "src/types/message";
import { shouldRedact } from "./secretRedactor";

const REDACTION_PLACEHOLDER = "***";
const SCHEMA_VERSION = 1 as const;

export interface SessionRecord {
  schemaVersion: 1;
  id: string;
  createdAt: string;
  updatedAt: string;
  cwd: string;
  provider: string;
  model?: string;
  firstPrompt: string;
  stackNames: string[];
  messages: Message[]; // already redacted
}

export interface SessionIndexEntry {
  id: string;
  createdAt: string;
  updatedAt: string;
  firstPrompt: string;
  stackNames: string[];
}

/** Warn when resuming a session saved under a different working directory. */
export function sessionCwdMismatchWarning(record: SessionRecord, cwd: string): string | undefined {
  if (record.cwd === cwd) return undefined;
  return `Resuming session saved in ${record.cwd} (current directory: ${cwd}). Stack paths may differ.`;
}

/** Format index entries for /sessions output (newest-first). */
export function formatSessionsList(entries: SessionIndexEntry[]): string {
  if (entries.length === 0) return "No saved sessions.";
  return [
    "Saved sessions (newest first):",
    ...entries.map((entry, index) => {
      const stacks =
        entry.stackNames.length > 0 ? `  stacks: ${entry.stackNames.join(", ")}` : "";
      const prompt =
        entry.firstPrompt.length > 72
          ? `${entry.firstPrompt.slice(0, 69)}...`
          : entry.firstPrompt;
      return [
        `${index + 1}. ${entry.id}`,
        `   updated: ${entry.updatedAt}${stacks}`,
        `   prompt: ${prompt}`,
      ].join("\n");
    }),
    "",
    "Resume with /resume or /resume <id>",
  ].join("\n");
}

function warn(message: string): void {
  process.stderr.write(`[docker-agent] ${message}\n`);
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Recursively walk a `Message[]` and replace any string value whose key matches
 * SECRET_KEY_PATTERN with the redaction placeholder.
 *
 * The only place secrets appear in tool messages is in environment maps embedded
 * in tool-result content strings. We scan:
 *   - ToolResultMessage.content (string) — look for KEY=VALUE patterns
 *   - AssistantMessage content blocks (text, tool_use inputs as JSON)
 *
 * For simplicity and safety we do a string-level replacement: any JSON field
 * whose key matches SECRET_KEY_PATTERN has its value replaced with "***".
 */
function redactMessages(messages: Message[]): Message[] {
  return messages.map((msg) => {
    if (msg.role === "tool") {
      return { ...msg, content: redactString(msg.content) };
    }
    if (msg.role === "assistant") {
      return {
        ...msg,
        content: msg.content.map((block) => {
          if (block.type === "text") {
            return { ...block, text: redactString(block.text) };
          }
          if (block.type === "tool_use") {
            return { ...block, input: redactValue(block.input) };
          }
          return block;
        }),
      };
    }
    // UserMessage: content is a plain string; may contain injected env
    if (msg.role === "user") {
      return { ...msg, content: redactString(msg.content) };
    }
    return msg;
  });
}

/**
 * Redact a plain string — looks for `KEY=VALUE` or `"KEY": "VALUE"` patterns
 * where KEY matches the secret pattern.
 */
function redactString(input: string): string {
  // Replace JSON-style: "secretKey": "someValue"
  let result = input.replace(
    /"([^"]+)"(\s*:\s*)"([^"]*)"/g,
    (_match, key: string, colon: string, _value: string) => {
      if (shouldRedact(key)) {
        return `"${key}"${colon}"${REDACTION_PLACEHOLDER}"`;
      }
      return _match;
    },
  );
  // Replace shell-style: SECRET_KEY=someValue (unquoted or quoted)
  result = result.replace(
    /(\b\w+\b)(=)("[^"]*"|'[^']*'|[^\s,}]+)/g,
    (_match, key: string, eq: string, value: string) => {
      if (shouldRedact(key)) {
        return `${key}${eq}${REDACTION_PLACEHOLDER}`;
      }
      return _match;
    },
  );
  return result;
}

/**
 * Recursively redact an arbitrary JSON-serializable value (used for tool_use inputs).
 */
function redactValue(value: unknown): unknown {
  if (value === null || value === undefined) return value;
  if (typeof value === "string") return redactString(value);
  if (Array.isArray(value)) return value.map(redactValue);
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const result: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj)) {
      result[k] = shouldRedact(k) ? REDACTION_PLACEHOLDER : redactValue(v);
    }
    return result;
  }
  return value;
}

export class SessionStore {
  private readonly sessionsDir: string;
  private readonly indexPath: string;

  constructor(root: string) {
    this.sessionsDir = path.join(root, "sessions");
    this.indexPath = path.join(this.sessionsDir, "index.json");
    fs.mkdirSync(this.sessionsDir, { recursive: true });
  }

  /**
   * Persist a session record atomically and upsert the index.
   * Messages are run through the secret redactor before writing.
   * If the write fails, logs a warning and preserves the prior file.
   */
  save(record: SessionRecord): void {
    const existing = this.read(record.id);
    const createdAt = existing?.createdAt ?? record.createdAt;
    const redacted: SessionRecord = {
      ...record,
      createdAt,
      messages: redactMessages(record.messages),
    };

    const filePath = path.join(this.sessionsDir, `${record.id}.json`);
    const tmpPath = `${filePath}.tmp`;

    try {
      fs.writeFileSync(tmpPath, JSON.stringify(redacted, null, 2), {
        encoding: "utf-8",
        mode: 0o644,
      });
      fs.renameSync(tmpPath, filePath);
    } catch (err) {
      // Clean up tmp file if it was created
      try {
        fs.unlinkSync(tmpPath);
      } catch {
        /* ignore cleanup errors */
      }
      warn(`SessionStore.save failed for session ${record.id}: ${errorMessage(err)}`);
      return; // preserve prior file, do not re-throw
    }

    // Upsert index
    this.upsertIndex({
      id: record.id,
      createdAt: record.createdAt,
      updatedAt: record.updatedAt,
      firstPrompt: record.firstPrompt,
      stackNames: record.stackNames,
    });
  }

  /**
   * Read a session record by id.
   * Returns null and warns on missing, corrupt, or wrong-schema files.
   * Never throws.
   */
  read(id: string): SessionRecord | null {
    const filePath = path.join(this.sessionsDir, `${id}.json`);
    try {
      if (!fs.existsSync(filePath)) {
        return null;
      }
      const raw = fs.readFileSync(filePath, "utf-8");
      const parsed: unknown = JSON.parse(raw);
      return this.validateRecord(parsed, filePath);
    } catch (err) {
      warn(`SessionStore.read failed for session ${id}: ${errorMessage(err)}`);
      return null;
    }
  }

  /**
   * Returns the most recently updated session record, or null if none exist.
   * Never throws.
   */
  latest(): SessionRecord | null {
    const entries = this.list();
    if (entries.length === 0) return null;
    // list() returns newest-first; first entry is the most recent
    const entry = entries[0];
    if (!entry) return null;
    return this.read(entry.id);
  }

  /**
   * Returns all index entries sorted newest-first by updatedAt.
   * Returns [] on missing or corrupt index.
   * Never throws.
   */
  list(): SessionIndexEntry[] {
    try {
      if (!fs.existsSync(this.indexPath)) {
        return [];
      }
      const raw = fs.readFileSync(this.indexPath, "utf-8");
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) {
        warn("SessionStore.list: index.json is not an array, ignoring");
        return [];
      }
      const entries = parsed.filter(isValidIndexEntry);
      // Sort newest-first
      entries.sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
      return entries;
    } catch (err) {
      warn(`SessionStore.list failed: ${errorMessage(err)}`);
      return [];
    }
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private upsertIndex(entry: SessionIndexEntry): void {
    const tmpPath = `${this.indexPath}.tmp`;
    try {
      let entries: SessionIndexEntry[] = [];
      if (fs.existsSync(this.indexPath)) {
        try {
          const raw = fs.readFileSync(this.indexPath, "utf-8");
          const parsed: unknown = JSON.parse(raw);
          if (Array.isArray(parsed)) {
            entries = parsed.filter(isValidIndexEntry);
          }
        } catch {
          // Corrupt index — start fresh
          entries = [];
        }
      }

      // Exactly one entry per id — remove any prior entry for this id
      entries = entries.filter((e) => e.id !== entry.id);
      entries.push(entry);

      fs.writeFileSync(tmpPath, JSON.stringify(entries, null, 2), {
        encoding: "utf-8",
        mode: 0o644,
      });
      fs.renameSync(tmpPath, this.indexPath);
    } catch (err) {
      try {
        fs.unlinkSync(tmpPath);
      } catch {
        /* ignore */
      }
      warn(`SessionStore.upsertIndex failed: ${errorMessage(err)}`);
    }
  }

  private validateRecord(parsed: unknown, source: string): SessionRecord | null {
    if (typeof parsed !== "object" || parsed === null) {
      warn(`SessionStore: corrupt session file at ${source} (not an object)`);
      return null;
    }
    const obj = parsed as Record<string, unknown>;
    if (obj.schemaVersion !== SCHEMA_VERSION) {
      warn(
        `SessionStore: unrecognised schemaVersion ${String(obj.schemaVersion)} at ${source}; expected ${SCHEMA_VERSION}`,
      );
      return null;
    }
    // Basic structural validation — we trust the file if schemaVersion is correct
    if (
      typeof obj.id !== "string" ||
      typeof obj.createdAt !== "string" ||
      typeof obj.updatedAt !== "string" ||
      typeof obj.cwd !== "string" ||
      typeof obj.provider !== "string" ||
      typeof obj.firstPrompt !== "string" ||
      !Array.isArray(obj.stackNames) ||
      !Array.isArray(obj.messages)
    ) {
      warn(`SessionStore: corrupt session file at ${source} (missing required fields)`);
      return null;
    }
    return parsed as SessionRecord;
  }
}

function isValidIndexEntry(entry: unknown): entry is SessionIndexEntry {
  if (typeof entry !== "object" || entry === null) return false;
  const obj = entry as Record<string, unknown>;
  return (
    typeof obj.id === "string" &&
    typeof obj.createdAt === "string" &&
    typeof obj.updatedAt === "string" &&
    typeof obj.firstPrompt === "string" &&
    Array.isArray(obj.stackNames)
  );
}
