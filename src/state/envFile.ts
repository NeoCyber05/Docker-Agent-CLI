import * as fs from "node:fs";
import * as path from "node:path";

export function parseEnvFile(content: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const rawLine of content.split("\n")) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq < 0) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    // strip inline comment
    const hash = value.indexOf(" #");
    if (hash >= 0) value = value.slice(0, hash).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    out[key] = value;
  }
  return out;
}

export function mergeEnv(
  fromEnvFile: Record<string, string>,
  inlineEnvironment: Record<string, string>,
): Record<string, string> {
  return { ...fromEnvFile, ...inlineEnvironment };
}

export function generateEnvFileContent(values: Record<string, string>): string {
  return (
    Object.entries(values)
      .map(([k, v]) => {
        const needsQuotes = /\s/.test(v);
        const escaped = v.replace(/\\/g, "\\\\").replace(/\n/g, "\\n").replace(/"/g, '\\"');
        return needsQuotes ? `${k}="${escaped}"` : `${k}=${escaped}`;
      })
      .join("\n") + "\n"
  );
}

export interface FsDeps {
  writeFileSync: (p: string, c: string, opts: { mode: number }) => void;
  mkdirSync: (p: string, opts?: { recursive: boolean }) => void;
}

const realFs: FsDeps = {
  writeFileSync: (p, c, opts) => fs.writeFileSync(p, c, opts),
  mkdirSync: (p, opts) => fs.mkdirSync(p, opts),
};

export function writeEnvFile(
  filePath: string,
  values: Record<string, string>,
  deps: FsDeps = realFs,
): void {
  deps.mkdirSync(path.dirname(filePath), { recursive: true });
  deps.writeFileSync(filePath, generateEnvFileContent(values), { mode: 0o600 });
}

export function readEnvFile(filePath: string): Record<string, string> {
  if (!fs.existsSync(filePath)) return {};
  return parseEnvFile(fs.readFileSync(filePath, "utf-8"));
}
