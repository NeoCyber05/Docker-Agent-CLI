import { spawn as realSpawn } from "node:child_process";

export interface Spawner {
  spawn(cmd: string, args: string[], opts: { cwd: string }): AsyncGenerator<string, number>;
}

const defaultSpawner: Spawner = {
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
    out.on("data", (chunk: string) => pushChunk(chunk));
    err.on("data", (chunk: string) => pushChunk(chunk));
    const exitPromise = new Promise<number>((res) =>
      child.on("close", (code: number | null) => {
        pushChunk(null);
        res(code ?? 0);
      }),
    );
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
    if (opts.tailLines !== undefined) args.push("--tail", String(opts.tailLines));
    if (opts.service) args.push(opts.service);
    return yield* this.spawner.spawn("docker", args, { cwd: this.cwd });
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
