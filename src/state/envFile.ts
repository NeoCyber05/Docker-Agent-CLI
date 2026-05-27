import * as fs from "node:fs";
import * as path from "node:path";

export function parseEnvFile(content: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const rawLine of content.split("\n")) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    const value = parseEnvValue(line.slice(eq + 1).trim());
    if (value === undefined) continue;
    out[key] = value;
  }
  return out;
}

function parseEnvValue(value: string): string | undefined {
  if (value.startsWith('"') || value.startsWith("'")) {
    const quote = value.startsWith('"') ? '"' : "'";
    const close = value.indexOf(quote, 1);
    if (close < 0) return undefined;
    const trailing = value.slice(close + 1).trim();
    if (trailing && !trailing.startsWith("#")) return undefined;
    return value.slice(1, close);
  }

  const hash = value.indexOf(" #");
  return (hash >= 0 ? value.slice(0, hash) : value).trim();
}

export type EnvValue = string | number | boolean;

export function mergeEnv(
  fromEnvFile: Record<string, string>,
  inlineEnvironment: Record<string, EnvValue>,
): Record<string, string> {
  const merged = { ...fromEnvFile };
  for (const [key, value] of Object.entries(inlineEnvironment)) {
    merged[key] = String(value);
  }
  return merged;
}

export function generateEnvFileContent(values: Record<string, string>): string {
  const lines = Object.entries(values).map(([k, v]) => {
    assertSupportedEnvFileValue(k, v);
    const needsQuotes = /\s/.test(v) || v.startsWith("#");
    return needsQuotes ? `${k}="${v}"` : `${k}=${v}`;
  });
  return lines.length > 0 ? `${lines.join("\n")}\n` : "";
}

function assertSupportedEnvFileValue(key: string, value: string): void {
  if (value.includes('"') || value.includes("\n") || value.includes("\r") || value.includes("\0")) {
    throw new Error(`Unsupported env_file value for ${key}`);
  }
}

export interface FsDeps {
  writeFileSync: (p: string, c: string, opts: { mode: number }) => void;
  mkdirSync: (p: string, opts?: { recursive: boolean }) => unknown;
  existsSync: (p: string) => boolean;
  readFileSync: (p: string, encoding: "utf-8") => string;
}

const realFs: FsDeps = {
  writeFileSync: (p, c, opts) => fs.writeFileSync(p, c, opts),
  mkdirSync: (p, opts) => fs.mkdirSync(p, opts),
  existsSync: (p) => fs.existsSync(p),
  readFileSync: (p, encoding) => fs.readFileSync(p, encoding),
};

export function writeEnvFile(
  filePath: string,
  values: Record<string, string>,
  deps: Pick<FsDeps, "writeFileSync" | "mkdirSync"> = realFs,
): void {
  void deps.mkdirSync(path.dirname(filePath), { recursive: true });
  deps.writeFileSync(filePath, generateEnvFileContent(values), { mode: 0o600 });
}

export function readEnvFile(
  filePath: string,
  deps: Pick<FsDeps, "existsSync" | "readFileSync"> = realFs,
): Record<string, string> {
  if (!deps.existsSync(filePath)) return {};
  return parseEnvFile(deps.readFileSync(filePath, "utf-8"));
}
