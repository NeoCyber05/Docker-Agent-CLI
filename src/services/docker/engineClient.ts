import Docker from "dockerode";
import { z } from "zod";

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
  State: { Status: string; Health?: { Status: string } | undefined };
  Config: { Image: string; Env: string[]; Cmd: string[] | null; Labels: Record<string, string> };
  HostConfig: { Binds: string[] | null; PortBindings: Record<string, unknown> };
  NetworkSettings: { Ports: Record<string, Array<{ HostIp: string; HostPort: string }> | null> };
}

const containerSummarySchema = z.object({
  Id: z.string(),
  Names: z.array(z.string()),
  State: z.string(),
  Labels: z.record(z.string()),
});

const portBindingSchema = z.object({
  HostIp: z.string(),
  HostPort: z.string(),
});

const containerInspectSchema = z.object({
  Id: z.string(),
  Name: z.string(),
  State: z.object({
    Status: z.string(),
    Health: z
      .object({
        Status: z.string(),
      })
      .optional(),
  }),
  Config: z.object({
    Image: z.string(),
    Env: z.array(z.string()),
    Cmd: z.array(z.string()).nullable(),
    Labels: z.record(z.string()),
  }),
  HostConfig: z.object({
    Binds: z.array(z.string()).nullable(),
    PortBindings: z.record(z.unknown()),
  }),
  NetworkSettings: z.object({
    Ports: z.record(z.array(portBindingSchema).nullable()),
  }),
});

export function createEngineClient(): EngineClient {
  const docker = new Docker();
  return {
    listContainers: async (opts) => {
      const listOptions: Docker.ContainerListOptions = { all: opts.all ?? false };
      if (opts.filters) listOptions.filters = JSON.stringify(opts.filters);
      const containers = await docker.listContainers(listOptions);
      return containers.map((container) => containerSummarySchema.parse(container));
    },
    inspect: async (id) => containerInspectSchema.parse(await docker.getContainer(id).inspect()),
  };
}
