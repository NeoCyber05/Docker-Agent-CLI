import { vi } from "vitest";

export class MockDockerEngine {
  containers: Array<{
    Id: string;
    Names: string[];
    State: string;
    Labels: Record<string, string>;
    Config?: { Env?: string[]; Cmd?: string[]; Image?: string };
  }> = [];
  localImages = new Map<
    string,
    {
      Id: string;
      RepoTags: string[];
      Size: number;
      Architecture: string;
      Os: string;
      Created: string;
    } | null
  >();
  pullImageLines: string[] = [];
  listContainers = vi.fn(
    async (_opts: { all?: boolean; filters?: unknown } = {}) => this.containers,
  );
  inspect = vi.fn(async (id: string) => this.containers.find((c) => c.Id === id) ?? {});
  getContainer = vi.fn((id: string) => ({
    inspect: vi.fn(async () => this.containers.find((c) => c.Id === id) ?? {}),
  }));
  inspectImage = vi.fn(async (nameOrId: string) => {
    if (this.localImages.has(nameOrId)) return this.localImages.get(nameOrId) ?? null;
    return {
      Id: `sha256:${nameOrId}`,
      RepoTags: [nameOrId],
      Size: 1,
      Architecture: "amd64",
      Os: "linux",
      Created: "2026-01-01T00:00:00.000Z",
    };
  });
  listImages = vi.fn(async () =>
    [...this.localImages.values()].filter(
      (
        image,
      ): image is {
        Id: string;
        RepoTags: string[];
        Size: number;
        Architecture: string;
        Os: string;
        Created: string;
      } => image !== null,
    ),
  );
  pullImage = vi.fn(
    async function* (
      this: MockDockerEngine,
      _image: string,
      _opts: { signal?: AbortSignal } = {},
    ): AsyncGenerator<string, void> {
      for (const line of this.pullImageLines) yield line;
    }.bind(this),
  );
}
