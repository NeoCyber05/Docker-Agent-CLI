import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  generateEnvFileContent,
  mergeEnv,
  parseEnvFile,
  readEnvFile,
  writeEnvFile,
} from "src/state/envFile";
import { describe, expect, test } from "vitest";

describe("envFile parsing", () => {
  test("parses KEY=value lines", () => {
    expect(parseEnvFile("FOO=bar\nBAZ=qux\n")).toEqual({ FOO: "bar", BAZ: "qux" });
  });

  test("strips quotes around values", () => {
    expect(parseEnvFile("FOO=\"bar baz\"\nQUX='a b'\n")).toEqual({
      FOO: "bar baz",
      QUX: "a b",
    });
  });

  test("ignores comments and blank lines", () => {
    expect(parseEnvFile("# comment\nFOO=bar\n\n# another\n")).toEqual({ FOO: "bar" });
  });

  test("strips inline comments", () => {
    expect(parseEnvFile("FOO=bar # comment\n")).toEqual({ FOO: "bar" });
  });

  test("preserves hash characters inside quoted values", () => {
    expect(parseEnvFile('FOO="hello # not-comment"\n')).toEqual({
      FOO: "hello # not-comment",
    });
  });

  test("ignores empty keys and unbalanced quoted values", () => {
    expect(parseEnvFile('=value\nFOO="unclosed\nBAR=ok\n')).toEqual({ BAR: "ok" });
  });

  test("inline override beats env_file", () => {
    const fromFile = { A: "1", B: "2" };
    const inline = { B: 9, C: true };
    expect(mergeEnv(fromFile, inline)).toEqual({ A: "1", B: "9", C: "true" });
  });

  test("generateEnvFileContent emits KEY=value lines", () => {
    expect(generateEnvFileContent({ A: "1", B: "two words" })).toBe('A=1\nB="two words"\n');
  });

  test("generateEnvFileContent round trips supported ASCII values", () => {
    const values = {
      PLAIN: "abc123",
      SPACE: "two words",
      LEADING_HASH: "#value",
      INTERNAL_HASH: "abc#123",
      BACKSLASH: "C:\\tmp\\file",
      SINGLE_QUOTE: "it's ok",
    };
    expect(parseEnvFile(generateEnvFileContent(values))).toEqual(values);
  });

  test("generateEnvFileContent rejects values Compose env_file cannot encode safely", () => {
    expect(() => generateEnvFileContent({ MSG: 'say "hello"' })).toThrow(
      /unsupported env_file value/i,
    );
    expect(() => generateEnvFileContent({ MSG: "line1\nline2" })).toThrow(
      /unsupported env_file value/i,
    );
    expect(() => generateEnvFileContent({ MSG: "line1\rline2" })).toThrow(
      /unsupported env_file value/i,
    );
  });

  test("generateEnvFileContent returns empty content for empty input", () => {
    expect(generateEnvFileContent({})).toBe("");
  });
});

describe("envFile write", () => {
  test("writeEnvFile uses 0o600 mode", () => {
    const fs = { writes: [] as Array<{ p: string; c: string; m: number }> };
    writeEnvFile(
      "/x/y.env",
      { K: "v" },
      {
        writeFileSync: (p: string, c: string, opts: { mode: number }) =>
          fs.writes.push({ p, c, m: opts.mode }),
        mkdirSync: () => {},
      },
    );
    expect(fs.writes[0]).toMatchObject({ p: "/x/y.env", m: 0o600 });
    expect(fs.writes[0]?.c).toContain("K=v");
  });
});

describe("readEnvFile", () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "docker-agent-envfile-test-"));

  test("returns empty object when file missing", () => {
    expect(readEnvFile(path.join(tmpDir, "missing.env"))).toEqual({});
  });

  test("reads and parses existing file", () => {
    const p = path.join(tmpDir, "test.env");
    fs.writeFileSync(p, "FOO=bar\n# comment\nBAZ=qux\n");
    expect(readEnvFile(p)).toEqual({ FOO: "bar", BAZ: "qux" });
  });

  test("reads through FsDeps when supplied", () => {
    const deps = {
      existsSync: () => true,
      readFileSync: () => 'FOO="bar baz"\n',
    };
    expect(readEnvFile("/fake/test.env", deps)).toEqual({ FOO: "bar baz" });
  });
});
