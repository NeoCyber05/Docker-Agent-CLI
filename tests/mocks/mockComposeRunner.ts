import { vi } from "vitest";

export interface ComposePsRow {
  Name: string;
  Service: string;
  State: string;
  Health?: string;
}

export class MockBoundRunner {
  spawnedArgs: string[];
  upCalls: Array<{ detach?: boolean; scale?: Record<string, number> }> = [];
  downCalls: Array<{ volumes?: boolean }> = [];
  psCalls: Array<{ json?: boolean }> = [];
  logsCalls: Array<{ service?: string; tailLines?: number }> = [];
  lastExitCode = 0;

  up = vi.fn(
    async function* (
      this: MockBoundRunner,
      opts: { detach?: boolean; scale?: Record<string, number> } = {},
    ): AsyncGenerator<string, number> {
      this.upCalls.push(opts);
      yield `up: ${this.stackName}\n`;
      this.lastExitCode = 0;
      return 0;
    }.bind(this),
  );

  down = vi.fn(
    async function* (
      this: MockBoundRunner,
      opts: { volumes?: boolean } = {},
    ): AsyncGenerator<string, number> {
      this.downCalls.push(opts);
      yield `down: ${this.stackName}\n`;
      this.lastExitCode = 0;
      return 0;
    }.bind(this),
  );

  ps = vi.fn(async (opts: { json?: boolean } = {}): Promise<ComposePsRow[]> => {
    this.psCalls.push(opts);
    return [];
  });

  logs = vi.fn(
    async function* (
      this: MockBoundRunner,
      opts: { service?: string; tailLines?: number } = {},
    ): AsyncGenerator<string, number> {
      this.logsCalls.push(opts);
      yield "";
      this.lastExitCode = 0;
      return 0;
    }.bind(this),
  );

  constructor(
    public stackName: string,
    public yamlPath: string,
    public cwd: string,
  ) {
    this.spawnedArgs = ["compose", "-p", stackName, "--project-directory", cwd, "-f", yamlPath];
  }
}

export class MockComposeRunner {
  forStackCalls: Array<{ stackName: string; yamlPath: string; cwd: string }> = [];
  private bound = new Map<string, MockBoundRunner>();
  forStack = vi.fn((stackName: string, yamlPath: string, cwd: string): MockBoundRunner => {
    this.forStackCalls.push({ stackName, yamlPath, cwd });
    const existing = this.bound.get(stackName);
    if (existing) return existing;
    const runner = new MockBoundRunner(stackName, yamlPath, cwd);
    this.bound.set(stackName, runner);
    return runner;
  });
  boundFor(stackName: string): MockBoundRunner {
    const b = this.bound.get(stackName);
    if (!b) throw new Error(`No bound runner for stack ${stackName}`);
    return b;
  }
}
