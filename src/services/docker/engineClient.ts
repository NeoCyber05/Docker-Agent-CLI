import Docker from "dockerode";

export interface EngineClient {
  listContainers(opts: {
    all?: boolean;
    filters?: { label?: string[] };
  }): Promise<Array<ContainerSummary>>;
  inspect(id: string): Promise<ContainerInspect>;
}

export interface ContainerSummary {
  Id: string;
  Names: string[];
  State: string;
  Labels: Record<string, string>;
}

export interface ContainerInspect {
  Id: string;
  Name: string;
  State: { Status: string; Health?: { Status: string } };
  Config: { Image: string; Env: string[]; Cmd: string[] | null; Labels: Record<string, string> };
  HostConfig: { Binds: string[] | null; PortBindings: Record<string, unknown> };
  NetworkSettings: { Ports: Record<string, Array<{ HostIp: string; HostPort: string }>> };
}

export function createEngineClient(): EngineClient {
  const docker = new Docker();
  return {
    listContainers: async (opts) =>
      (await docker.listContainers({
        all: opts.all ?? false,
        filters: opts.filters ? JSON.stringify(opts.filters) : undefined,
      } as unknown as { all?: boolean; filters?: string })) as unknown as ContainerSummary[],
    inspect: async (id) => (await docker.getContainer(id).inspect()) as ContainerInspect,
  };
}