import type { Readable } from "node:stream";
import Docker from "dockerode";
import { z } from "zod";

export interface EngineClient {
  listContainers(opts: {
    all?: boolean;
    filters?: { label?: string[] };
  }): Promise<Array<ContainerSummary>>;
  inspect(id: string): Promise<ContainerInspect>;
  inspectImage?(nameOrId: string): Promise<ImageInspect | null>;
  listImages?(opts?: { filters?: Record<string, string[]> }): Promise<ImageSummary[]>;
  pullImage?(image: string, opts?: { signal?: AbortSignal }): AsyncGenerator<string, void>;
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

export interface ImageSummary {
  Id: string;
  RepoTags: string[];
  Size: number;
  Created: number;
}

export interface ImageInspect {
  Id: string;
  RepoTags: string[];
  Size: number;
  Architecture: string;
  Os: string;
  Created: string;
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

const repoTagsSchema = z.preprocess((value) => value ?? [], z.array(z.string()));

const imageSummarySchema = z.object({
  Id: z.string(),
  RepoTags: repoTagsSchema,
  Size: z.number(),
  Created: z.number(),
});

const imageInspectSchema = z.object({
  Id: z.string(),
  RepoTags: repoTagsSchema,
  Size: z.number(),
  Architecture: z.string(),
  Os: z.string(),
  Created: z.string(),
});

function isNotFoundError(error: unknown): boolean {
  const candidate = error as {
    statusCode?: number;
    status?: number;
    reason?: string;
    message?: string;
  };
  return (
    candidate.statusCode === 404 ||
    candidate.status === 404 ||
    candidate.reason === "no such image" ||
    candidate.message?.toLowerCase().includes("no such image") === true
  );
}

function pullStream(docker: Docker, image: string): Promise<NodeJS.ReadableStream> {
  return docker.pull(image, {});
}

function formatPullProgressLine(line: string): string {
  try {
    const parsed = JSON.parse(line) as {
      id?: string;
      status?: string;
      progress?: string;
      error?: string;
    };
    if (parsed.error) return parsed.error;
    return [parsed.id, parsed.status, parsed.progress].filter(Boolean).join(" ");
  } catch {
    return line;
  }
}

async function* readPullProgress(
  stream: NodeJS.ReadableStream,
  signal?: AbortSignal,
): AsyncGenerator<string, void> {
  const readable = stream as Readable;
  let buffer = "";
  const abort = () => readable.destroy(new Error("Docker image pull aborted"));
  signal?.addEventListener("abort", abort, { once: true });
  stream.setEncoding("utf-8");
  try {
    for await (const chunk of stream as AsyncIterable<string>) {
      buffer += chunk;
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed) yield formatPullProgressLine(trimmed);
      }
    }
    const finalLine = buffer.trim();
    if (finalLine) yield formatPullProgressLine(finalLine);
  } finally {
    signal?.removeEventListener("abort", abort);
  }
}

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
    inspectImage: async (nameOrId) => {
      try {
        return imageInspectSchema.parse(await docker.getImage(nameOrId).inspect());
      } catch (error) {
        if (isNotFoundError(error)) return null;
        throw error;
      }
    },
    listImages: async (opts = {}) => {
      const dockerOpts: Docker.ListImagesOptions = {};
      if (opts.filters) dockerOpts.filters = JSON.stringify(opts.filters);
      const images = await docker.listImages(dockerOpts);
      return images.map((image) => imageSummarySchema.parse(image));
    },
    pullImage: async function* (image, opts = {}) {
      const stream = await pullStream(docker, image);
      yield* readPullProgress(stream, opts.signal);
    },
  };
}
