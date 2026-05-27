import { describe, expect, test } from "vitest";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { parseEnvFile, mergeEnv, writeEnvFile, generateEnvFileContent, readEnvFile } from "src/state/envFile";

describe("envFile parsing", () => {
  test("parses KEY=value lines", () => {
    expect(parseEnvFile("FOO=bar\nBAZ=qux\n")).toEqual({ FOO: "bar", BAZ: "qux" });
  });

  test("strips quotes around values", () => {
    expect(parseEnvFile('FOO="bar baz"\nQUX=\'a b\'\n')).toEqual({
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

  test("inline override beats env_file", () => {
    const fromFile = { A: "1", B: "2" };
    const inline = { B: "9", C: "3" };
    expect(mergeEnv(fromFile, inline)).toEqual({ A: "1", B: "9", C: "3" });
  });

  test("generateEnvFileContent emits KEY=value lines", () => {
    expect(generateEnvFileContent({ A: "1", B: "two words" })).toBe('A=1\nB="two words"\n');
  });

  test("generateEnvFileContent escapes inner double quotes", () => {
    expect(generateEnvFileContent({ MSG: 'say "hello"' })).toBe('MSG="say \\"hello\\""\n');
  });

  test("generateEnvFileContent escapes newlines", () => {
    expect(generateEnvFileContent({ A: "line1\nline2" })).toBe('A="line1\\nline2"\n');
  });
});

describe("envFile write", () => {
  test("writeEnvFile uses 0o600 mode", () => {
    const fs = { writes: [] as Array<{ p: string; c: string; m: number }> };
    writeEnvFile("/x/y.env", { K: "v" }, {
      writeFileSync: (p: string, c: string, opts: { mode: number }) =>
        fs.writes.push({ p, c, m: opts.mode }),
      mkdirSync: () => {},
    });
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
});
