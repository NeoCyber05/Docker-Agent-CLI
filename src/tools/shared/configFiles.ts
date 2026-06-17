import * as fs from "node:fs";
import * as path from "node:path";
import type { ServiceSpec } from "src/types/stack";

export interface BindMount {
  source: string;
  target: string;
  mode?: string;
}

export interface StagedConfigFile {
  path: string; // normalized, forward-slash, cwd-relative
  content: string;
  bytes: number;
}

const RESERVED_DIR = ".docker-agent";

/** Normalize a host-relative path to forward slashes with no leading "./". */
export function normalizeRel(p: string): string {
  const norm = path.normalize(p).split(path.sep).join("/");
  return norm.replace(/^\.\//, "");
}

/** Parse short-syntax volume "SOURCE:TARGET[:MODE]". Returns null for named volumes. */
export function parseBindMount(volume: string): BindMount | null {
  const parts = volume.split(":");
  if (parts.length < 2) return null;
  const source = parts[0] as string;
  const target = parts[1] as string;
  const mode = parts[2];
  // A bind mount's source is a filesystem path; named volumes start with an
  // alphanumeric. Windows absolute paths (C:\...) are out of scope.
  if (!/^[.~/]/.test(source)) return null;
  return mode ? { source, target, mode } : { source, target };
}

/** A bind source is "file-like" when its basename carries an extension. */
export function isFileLikeBind(source: string): boolean {
  return /\.[A-Za-z0-9]+$/.test(path.basename(source));
}

/** Confine a host-relative path to cwd. Rejects abs paths, traversal, reserved dirs. */
export function resolveSafe(
  cwd: string,
  relPath: string,
): { ok: true; abs: string } | { ok: false; error: string } {
  if (path.isAbsolute(relPath)) return { ok: false, error: "absolute paths are not allowed" };
  const abs = path.resolve(cwd, relPath);
  const rel = path.relative(cwd, abs);
  if (rel.startsWith("..") || path.isAbsolute(rel)) {
    return { ok: false, error: "path escapes the project directory" };
  }
  const first = normalizeRel(rel).split("/")[0];
  if (first === RESERVED_DIR) return { ok: false, error: `${RESERVED_DIR} is reserved` };
  return { ok: true, abs };
}

/** File-like bind mounts that have neither provided content nor an existing host file. */
export function detectMissingConfigFiles(
  services: Record<string, ServiceSpec>,
  providedKeys: Set<string>,
  cwd: string,
): Array<{ service: string; path: string }> {
  const missing: Array<{ service: string; path: string }> = [];
  for (const [service, spec] of Object.entries(services)) {
    for (const vol of spec.volumes ?? []) {
      const bind = parseBindMount(vol);
      if (!bind || !isFileLikeBind(bind.source)) continue;
      if (providedKeys.has(normalizeRel(bind.source))) continue;
      const safe = resolveSafe(cwd, bind.source);
      if (!safe.ok) continue; // unsafe paths are rejected during staging
      if (!fs.existsSync(safe.abs)) missing.push({ service, path: bind.source });
    }
  }
  return missing;
}

/**
 * File-like bind sources that would make `compose up` misbehave: the source is
 * absent (Docker silently auto-creates an empty *directory* there) or already
 * squats as a directory (mounting a dir onto an image file fails with "are you
 * trying to mount a directory onto a file"). Call this right before `up` so we
 * refuse loudly instead of letting Docker create a stray folder.
 */
export function findInvalidFileBinds(
  services: Record<string, ServiceSpec>,
  cwd: string,
): Array<{ service: string; path: string; reason: "missing" | "directory" }> {
  const bad: Array<{ service: string; path: string; reason: "missing" | "directory" }> = [];
  for (const [service, spec] of Object.entries(services)) {
    for (const vol of spec.volumes ?? []) {
      const bind = parseBindMount(vol);
      if (!bind || !isFileLikeBind(bind.source)) continue;
      const safe = resolveSafe(cwd, bind.source);
      if (!safe.ok) continue; // unsafe paths are rejected during staging
      if (!fs.existsSync(safe.abs)) {
        bad.push({ service, path: bind.source, reason: "missing" });
      } else if (fs.statSync(safe.abs).isDirectory()) {
        bad.push({ service, path: bind.source, reason: "directory" });
      }
    }
  }
  return bad;
}

const MAX_FILE_BYTES = 64 * 1024;
const MAX_TOTAL_BYTES = 256 * 1024;

export interface ConfigFileSnapshot {
  abs: string;
  existed: boolean;
  previousContent: string | null;
}

/** Validate provided configFiles against the services' file binds + size caps. */
export function stageConfigFiles(
  cwd: string,
  services: Record<string, ServiceSpec>,
  configFiles: Record<string, string> | undefined,
): { ok: true; staged: StagedConfigFile[] } | { ok: false; error: string } {
  const provided = configFiles ?? {};
  const fileBinds = new Set<string>();
  for (const spec of Object.values(services)) {
    for (const vol of spec.volumes ?? []) {
      const bind = parseBindMount(vol);
      if (bind && isFileLikeBind(bind.source)) fileBinds.add(normalizeRel(bind.source));
    }
  }
  let total = 0;
  const staged: StagedConfigFile[] = [];
  for (const [key, content] of Object.entries(provided)) {
    const safe = resolveSafe(cwd, key);
    if (!safe.ok) return { ok: false, error: `unsafe config file path "${key}": ${safe.error}` };
    const norm = normalizeRel(key);
    if (!fileBinds.has(norm)) {
      return { ok: false, error: `configFiles entry "${key}" matches no file bind mount` };
    }
    const bytes = Buffer.byteLength(content, "utf8");
    if (bytes > MAX_FILE_BYTES) return { ok: false, error: `config file "${key}" exceeds 64 KiB` };
    total += bytes;
    staged.push({ path: norm, content, bytes });
  }
  if (total > MAX_TOTAL_BYTES) return { ok: false, error: "config files total exceeds 256 KiB" };
  return { ok: true, staged };
}

export function snapshotConfigFiles(cwd: string, files: StagedConfigFile[]): ConfigFileSnapshot[] {
  return files.map((f) => {
    const abs = path.resolve(cwd, f.path);
    const existed = fs.existsSync(abs) && fs.statSync(abs).isFile();
    return {
      abs,
      existed,
      previousContent: existed ? fs.readFileSync(abs, "utf8") : null,
    };
  });
}

export function writeConfigFiles(cwd: string, files: StagedConfigFile[]): void {
  for (const f of files) {
    const safe = resolveSafe(cwd, f.path);
    if (!safe.ok) throw new Error(`refusing to write "${f.path}": ${safe.error}`);
    // Docker auto-creates an empty *directory* at a bind-mount source when the
    // file is missing at `compose up` time. If such a stale dir squats at our
    // target, remove it so writeFileSync lands a real file instead of throwing
    // EISDIR — and so the next mount sees a file, not a directory.
    if (fs.existsSync(safe.abs) && fs.statSync(safe.abs).isDirectory()) {
      fs.rmSync(safe.abs, { recursive: true, force: true });
    }
    fs.mkdirSync(path.dirname(safe.abs), { recursive: true });
    fs.writeFileSync(safe.abs, f.content, "utf8");
  }
}

export function restoreConfigFiles(snapshots: ConfigFileSnapshot[]): void {
  for (const s of snapshots) {
    if (s.existed) {
      fs.writeFileSync(s.abs, s.previousContent ?? "", "utf8");
    } else if (fs.existsSync(s.abs)) {
      // recursive covers a Docker-auto-created directory squatting at the path
      fs.rmSync(s.abs, { recursive: true, force: true });
    }
  }
}
