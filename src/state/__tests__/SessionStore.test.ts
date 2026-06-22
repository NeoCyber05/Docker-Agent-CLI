import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { Message } from "src/types/message";
import { afterEach, beforeEach, describe, expect, test } from "vitest";
import {
  type SessionRecord,
  SessionStore,
  formatSessionsList,
  sessionCwdMismatchWarning,
} from "../SessionStore";

function makeRecord(overrides: Partial<SessionRecord> = {}): SessionRecord {
  return {
    schemaVersion: 1,
    id: "sess-1",
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:01.000Z",
    cwd: "/project",
    provider: "gemini",
    firstPrompt: "deploy nginx",
    stackNames: ["web"],
    messages: [{ role: "user", content: "deploy nginx" }],
    ...overrides,
  };
}

describe("SessionStore", () => {
  let tmp: string;
  let store: SessionStore;

  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "session-store-"));
    store = new SessionStore(tmp);
  });

  afterEach(() => {
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  test("save and read round-trip", () => {
    const record = makeRecord();
    store.save(record);
    expect(store.read("sess-1")).toEqual(record);
  });

  test("preserves createdAt on overwrite", () => {
    store.save(makeRecord({ updatedAt: "2026-01-01T00:00:01.000Z" }));
    store.save(
      makeRecord({
        createdAt: "2026-06-01T00:00:00.000Z",
        updatedAt: "2026-06-01T00:00:02.000Z",
        messages: [
          { role: "user", content: "deploy nginx" },
          { role: "user", content: "add redis" },
        ],
      }),
    );
    const read = store.read("sess-1");
    expect(read?.createdAt).toBe("2026-01-01T00:00:00.000Z");
    expect(read?.updatedAt).toBe("2026-06-01T00:00:02.000Z");
  });

  test("redacts secrets in messages before writing", () => {
    const messages: Message[] = [
      {
        role: "assistant",
        content: [
          {
            type: "tool_use",
            id: "t1",
            name: "apply_stack",
            input: { API_KEY: "hunter2", image: "nginx" },
          },
        ],
      },
    ];
    store.save(makeRecord({ messages }));
    const raw = fs.readFileSync(path.join(tmp, "sessions", "sess-1.json"), "utf-8");
    expect(raw).not.toContain("hunter2");
    expect(raw).toContain("***");
  });

  test("list returns newest-first index entries", () => {
    store.save(
      makeRecord({
        id: "older",
        createdAt: "2026-01-01T00:00:00.000Z",
        updatedAt: "2026-01-01T00:00:00.000Z",
        firstPrompt: "old",
      }),
    );
    store.save(
      makeRecord({
        id: "newer",
        createdAt: "2026-02-01T00:00:00.000Z",
        updatedAt: "2026-02-01T00:00:00.000Z",
        firstPrompt: "new",
      }),
    );
    const list = store.list();
    expect(list.map((entry) => entry.id)).toEqual(["newer", "older"]);
  });

  test("latest returns most recently updated session", () => {
    store.save(makeRecord({ id: "a", updatedAt: "2026-01-01T00:00:00.000Z" }));
    store.save(makeRecord({ id: "b", updatedAt: "2026-02-01T00:00:00.000Z" }));
    expect(store.latest()?.id).toBe("b");
  });

  test("read returns null for missing or corrupt files", () => {
    expect(store.read("missing")).toBeNull();
    fs.mkdirSync(path.join(tmp, "sessions"), { recursive: true });
    fs.writeFileSync(path.join(tmp, "sessions", "bad.json"), "{not json");
    expect(store.read("bad")).toBeNull();
    fs.writeFileSync(
      path.join(tmp, "sessions", "wrong-schema.json"),
      JSON.stringify({ schemaVersion: 9 }),
    );
    expect(store.read("wrong-schema")).toBeNull();
  });
});

describe("session helpers", () => {
  test("sessionCwdMismatchWarning only warns on mismatch", () => {
    const record = makeRecord({ cwd: "/other" });
    expect(sessionCwdMismatchWarning(record, "/project")).toContain("/other");
    expect(sessionCwdMismatchWarning(record, "/other")).toBeUndefined();
  });

  test("formatSessionsList handles empty and populated lists", () => {
    expect(formatSessionsList([])).toBe("No saved sessions.");
    const formatted = formatSessionsList([
      {
        id: "sess-1",
        createdAt: "2026-01-01T00:00:00.000Z",
        updatedAt: "2026-02-01T00:00:00.000Z",
        firstPrompt: "deploy stack",
        stackNames: ["web", "db"],
      },
    ]);
    expect(formatted).toContain("sess-1");
    expect(formatted).toContain("stacks: web, db");
    expect(formatted).toContain("/resume");
  });
});
