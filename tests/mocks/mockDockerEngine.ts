import { vi } from "vitest";

export class MockDockerEngine {
  containers: Array<{
    Id: string;
    Names: string[];
    State: string;
    Labels: Record<string, string>;
    Config?: { Env?: string[]; Cmd?: string[]; Image?: string };
  }> = [];
  listContainers = vi.fn(
    async (_opts: { all?: boolean; filters?: unknown } = {}) => this.containers,
  );
  getContainer = vi.fn((id: string) => ({
    inspect: vi.fn(async () => this.containers.find((c) => c.Id === id) ?? {}),
  }));
}
