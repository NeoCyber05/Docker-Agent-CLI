import { spawn as realSpawn } from "node:child_process";

export interface Spawner {
  spawn(
    cmd: string,
    args: string[],
    opts: { cwd: string; signal?: AbortSignal },
  ): AsyncGenerator<string, number>;
}

// Exported so the abort-ordering behavior can be unit-tested directly.
export const defaultSpawner: Spawner = {
  spawn: async function* spawn(cmd, args, opts) {
    const child = realSpawn(cmd, args, { cwd: opts.cwd, stdio: ["ignore", "pipe", "pipe"] });
    const out = child.stdout;
    const err = child.stderr;
    out.setEncoding("utf-8");
    err.setEncoding("utf-8");
    let lineBuffer = "";
    let resolveChunk: ((v: string | null) => void) | null = null;
    const chunkQueue: Array<string | null> = [];
    const pushChunk = (chunk: string | null) => {
      if (resolveChunk) {
        resolveChunk(chunk);
        resolveChunk = null;
      } else {
        chunkQueue.push(chunk);
      }
    };
    // Register stream + close listeners FIRST so an already-aborted signal
    // (handled below) cannot kill the child before `close` is observable.
    out.on("data", (chunk: string) => pushChunk(chunk));
    err.on("data", (chunk: string) => pushChunk(chunk));
    const exitPromise = new Promise<number>((res) =>
      child.on("close", (code: number | null) => {
        pushChunk(null);
        res(code ?? 0);
      }),
    );
    const onAbort = () => {
      child.kill("SIGTERM");
      pushChunk(null);
    };
    if (opts.signal) {
      if (opts.signal.aborted) onAbort();
      else opts.signal.addEventListener("abort", onAbort, { once: true });
    }
    try {
      while (true) {
        let chunk: string | null;
        if (chunkQueue.length > 0) {
          chunk = chunkQueue.shift() ?? null;
        } else {
          chunk = await new Promise<string | null>((res) => {
            resolveChunk = res;
          });
        }
        if (chunk === null) {
          if (lineBuffer.length > 0) yield lineBuffer;
          break;
        }
        lineBuffer += chunk;
        const lines = lineBuffer.split("\n");
        lineBuffer = lines.pop() ?? "";
        for (const line of lines) {
          yield `${line}\n`;
        }
      }
    } finally {
      opts.signal?.removeEventListener("abort", onAbort);
      // If the consumer stopped early (e.g. `break` out of the for-await without
      // aborting), the generator returns here and `await exitPromise` below is
      // skipped — so kill any still-running child to avoid leaking a `logs -f`
      // subprocess. No-op on the normal-close and abort paths (child already gone).
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
    }
    return await exitPromise;
  },
};

export interface UpOpts {
  detach?: boolean;
  scale?: Record<string, number>;
}
export interface DownOpts {
  volumes?: boolean;
}
export interface PsOpts {
  json?: boolean;
}
export interface LogsOpts {
  service?: string;
  tailLines?: number;
  follow?: boolean;
  since?: string;
  signal?: AbortSignal;
}
export interface ComposePsRow {
  Name: string;
  Service: string;
  State: string;
  Health?: string;
}

export class BoundComposeRunner {
  constructor(
    public readonly stackName: string,
    public readonly yamlPath: string,
    public readonly cwd: string,
    private spawner: Spawner,
  ) {}

  private baseArgs(): string[] {
    return ["compose", "-p", this.stackName, "--project-directory", this.cwd, "-f", this.yamlPath];
  }

  async *up(opts: UpOpts = {}): AsyncGenerator<string, number> {
    const args = this.baseArgs();
    args.push("up");
    if (opts.detach) args.push("-d");
    for (const [svc, n] of Object.entries(opts.scale ?? {})) args.push("--scale", `${svc}=${n}`);
    return yield* this.spawner.spawn("docker", args, { cwd: this.cwd });
  }

  async *down(opts: DownOpts = {}): AsyncGenerator<string, number> {
    const args = this.baseArgs();
    args.push("down");
    if (opts.volumes) args.push("-v");
    return yield* this.spawner.spawn("docker", args, { cwd: this.cwd });
  }

  async ps(opts: PsOpts = {}): Promise<ComposePsRow[]> {
    const args = this.baseArgs();
    args.push("ps");
    if (opts.json) args.push("--format", "json");
    const rows: ComposePsRow[] = [];
    let acc = "";
    const gen = this.spawner.spawn("docker", args, { cwd: this.cwd });
    while (true) {
      const r = await gen.next();
      if (r.done) break;
      acc += r.value;
    }
    for (const line of acc.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        rows.push(JSON.parse(trimmed) as ComposePsRow);
      } catch {
        /* ignore non-JSON */
      }
    }
    return rows;
  }

  async *logs(opts: LogsOpts = {}): AsyncGenerator<string, number> {
    const args = this.baseArgs();
    args.push("logs");
    if (opts.follow) args.push("-f");
    if (opts.tailLines !== undefined) args.push("--tail", String(opts.tailLines));
    if (opts.since !== undefined) args.push("--since", opts.since);
    if (opts.service) args.push(opts.service);
    return yield* this.spawner.spawn("docker", args, {
      cwd: this.cwd,
      ...(opts.signal ? { signal: opts.signal } : {}),
    });
  }
}

export class ComposeRunner {
  constructor(
    private cwd: string,
    private spawner: Spawner = defaultSpawner,
  ) {}
  forStack(stackName: string, yamlPath: string): BoundComposeRunner {
    return new BoundComposeRunner(stackName, yamlPath, this.cwd, this.spawner);
  }
}
