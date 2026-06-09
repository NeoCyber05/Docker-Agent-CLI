import * as fs from "node:fs";
import * as path from "node:path";
import type { StackDefinition, StackSummary } from "src/types/stack";
import { parse as parseYaml, stringify as stringifyYaml } from "yaml";
import { z } from "zod";
import { shouldRedact } from "./secretRedactor";

const serviceSpecSchema = z.object({
  image: z.string(),
  command: z.union([z.string(), z.array(z.string())]).optional(),
  ports: z.array(z.string()).optional(),
  environment: z.record(z.string()).optional(),
  env_file: z.array(z.string()).optional(),
  volumes: z.array(z.string()).optional(),
  depends_on: z
    .union([
      z.array(z.string()),
      z.record(
        z.object({
          condition: z.enum([
            "service_started",
            "service_healthy",
            "service_completed_successfully",
          ]),
        }),
      ),
    ])
    .optional(),
  healthcheck: z
    .object({
      test: z.union([z.string(), z.array(z.string())]),
      interval: z.string().optional(),
      timeout: z.string().optional(),
      retries: z.number().optional(),
      start_period: z.string().optional(),
    })
    .optional(),
  restart: z.enum(["no", "always", "on-failure", "unless-stopped"]).optional(),
  labels: z.record(z.string()).optional(),
  networks: z.array(z.string()).optional(),
  scale: z.number().optional(),
});

const stackDefinitionSchema = z.object({
  "x-docker-agent": z.object({
    name: z.string(),
    createdAt: z.string(),
    lastApplied: z.string().nullable(),
    intent: z.string(),
    provider: z.string(),
    generatedBy: z.string(),
    envFileSources: z.record(
      z.object({
        generated: z.boolean(),
        path: z.string(),
        addedKeys: z.array(z.string()).optional(),
      }),
    ),
  }),
  services: z.record(serviceSpecSchema),
  networks: z.record(z.unknown()).optional(),
  volumes: z.record(z.unknown()).optional(),
});

export interface HistoryEvent {
  ts: string;
  sessionId: string;
  stackName: string;
  action: "plan" | "apply" | "destroy" | "drift_detected" | "rollback" | "remediate";
  details: Record<string, unknown>;
}

export interface StateStoreOptions {
  warn?: (message: string) => void;
}

function formatZodIssues(error: z.ZodError): string {
  return error.issues
    .map((issue) => `${issue.path.join(".") || "<root>"}: ${issue.message}`)
    .join("; ");
}

export function parseStackDefinition(raw: unknown, source: string): StackDefinition {
  const result = stackDefinitionSchema.safeParse(raw);
  if (!result.success) {
    throw new Error(`Invalid stack state at ${source}: ${formatZodIssues(result.error)}`);
  }
  return result.data as StackDefinition;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return !(err instanceof Error && "code" in err && err.code === "ESRCH");
  }
}

export class StateStore {
  private readonly warn: (message: string) => void;

  constructor(
    private root: string,
    opts: StateStoreOptions = {},
  ) {
    this.warn = opts.warn ?? ((message) => console.warn(`[docker-agent] ${message}`));
    fs.mkdirSync(path.join(root, "stacks"), { recursive: true });
    fs.mkdirSync(path.join(root, "stacks", ".archive"), { recursive: true });
    fs.mkdirSync(path.join(root, "sessions"), { recursive: true });
    fs.mkdirSync(path.join(root, "locks"), { recursive: true });
    fs.mkdirSync(path.join(root, "logs"), { recursive: true });
    fs.mkdirSync(path.join(root, "secrets"), { recursive: true, mode: 0o700 });
  }

  private stackPath(name: string): string {
    return path.join(this.root, "stacks", `${name}.yaml`);
  }

  read(stackName: string): StackDefinition | null {
    const p = this.stackPath(stackName);
    if (!fs.existsSync(p)) return null;
    return this.readStackFile(p);
  }

  write(stackName: string, def: StackDefinition): void {
    const target = this.stackPath(stackName);
    const tmp = `${target}.tmp`;
    fs.writeFileSync(tmp, stringifyYaml(def), { mode: 0o644 });
    fs.renameSync(tmp, target);
  }

  list(): StackSummary[] {
    const dir = path.join(this.root, "stacks");
    const entries = fs
      .readdirSync(dir, { withFileTypes: true })
      .filter((e) => e.isFile() && e.name.endsWith(".yaml"));
    const stacks: StackSummary[] = [];
    for (const e of entries) {
      const p = path.join(dir, e.name);
      try {
        const def = this.readStackFile(p);
        stacks.push({
          name: def["x-docker-agent"].name,
          serviceCount: Object.keys(def.services).length,
          lastApplied: def["x-docker-agent"].lastApplied,
        });
      } catch (err) {
        this.warn(`Skipping invalid stack state at ${p}: ${errorMessage(err)}`);
      }
    }
    return stacks;
  }

  remove(stackName: string, archive = true): void {
    const src = this.stackPath(stackName);
    if (!fs.existsSync(src)) return;
    if (archive) {
      const ts = new Date().toISOString().replace(/[:.]/g, "-");
      const dst = path.join(this.root, "stacks", ".archive", `${stackName}-${ts}.yaml`);
      fs.renameSync(src, dst);
      // Timestamped files are durable history; this stable copy is the latest archived state.
      fs.copyFileSync(dst, path.join(this.root, "stacks", ".archive", `${stackName}.yaml`));
    } else {
      fs.unlinkSync(src);
    }
  }

  readArchive(stackName: string): StackDefinition | null {
    const p = path.join(this.root, "stacks", ".archive", `${stackName}.yaml`);
    if (!fs.existsSync(p)) return null;
    try {
      return this.readStackFile(p);
    } catch (err) {
      this.warn(`readArchive: could not parse archive for ${stackName}: ${errorMessage(err)}`);
      return null;
    }
  }

  hasArchiveMarker(stackName: string): boolean {
    const archiveDir = path.join(this.root, "stacks", ".archive");
    try {
      const entries = fs.readdirSync(archiveDir);
      return entries.some((name) => name.startsWith(stackName) && name.endsWith(".yaml"));
    } catch {
      return false;
    }
  }

  appendHistory(event: HistoryEvent): void {
    fs.appendFileSync(path.join(this.root, "history.json"), `${JSON.stringify(event)}\n`);
  }

  async acquireLock(stackName: string, opts: { timeoutMs?: number } = {}): Promise<() => void> {
    const lockPath = path.join(this.root, "locks", `${stackName}.lock`);
    const deadline = Date.now() + (opts.timeoutMs ?? 0);
    while (true) {
      try {
        const fd = fs.openSync(lockPath, "wx");
        fs.writeSync(fd, String(process.pid));
        fs.closeSync(fd);
        return () => {
          try {
            fs.unlinkSync(lockPath);
          } catch {
            /* noop */
          }
        };
      } catch {
        if (this.removeStaleLock(lockPath)) continue;
        if (Date.now() >= deadline) {
          throw new Error(`acquireLock: lock held for ${stackName}`);
        }
        await new Promise((r) => setTimeout(r, 10));
      }
    }
  }

  summary(): string {
    const stacks = this.list();
    const out: Record<string, unknown> = {};
    for (const s of stacks) {
      const def = this.read(s.name);
      if (!def) continue;
      out[s.name] = {
        lastApplied: def["x-docker-agent"].lastApplied,
        services: Object.fromEntries(
          Object.entries(def.services).map(([svc, spec]) => {
            const env = spec.environment ?? {};
            const visibleEnv: Record<string, string> = {};
            for (const [k, v] of Object.entries(env)) {
              visibleEnv[k] = shouldRedact(k) ? "***" : v;
            }
            return [
              svc,
              {
                image: spec.image,
                ports: spec.ports ?? [],
                scale: spec.scale ?? 1,
                environment: visibleEnv,
                // Paths are safe to expose; secret values live in the env files, not stack YAML.
                env_file: spec.env_file ?? [],
              },
            ];
          }),
        ),
      };
    }
    return stringifyYaml(out);
  }

  private readStackFile(p: string): StackDefinition {
    return parseStackDefinition(parseYaml(fs.readFileSync(p, "utf-8")), p);
  }

  private removeStaleLock(lockPath: string): boolean {
    try {
      const pid = Number.parseInt(fs.readFileSync(lockPath, "utf-8").trim(), 10);
      if (Number.isInteger(pid) && pid > 0 && isProcessAlive(pid)) return false;
      fs.unlinkSync(lockPath);
      return true;
    } catch {
      return false;
    }
  }
}
