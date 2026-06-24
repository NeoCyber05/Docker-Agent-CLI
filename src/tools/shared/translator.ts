import type { ToolContext } from "../../Tool";
import type { ServiceSpec } from "../../types/stack";
import type { StackDraft, HybridServiceIntent } from "./specSchemas";
import * as crypto from "node:crypto";
import { injectDbHealthchecks } from "./dbHealthcheck";

export interface PreparedStack {
  stackName: string;
  intent: string;
  services: Record<string, ServiceSpec>;
  networks: Record<string, any>;
  volumes: Record<string, any>;
  configFiles?: Record<string, string>;
  hash: string;
}

// Allowed Catalog Entries
const CATALOG_REGISTRY: Record<
  string,
  {
    image: string;
    containerPort: number;
    defaultEnv: Record<string, string>;
    healthcheck?: { test: string[]; interval: string; timeout: string; retries: number; start_period?: string };
    defaultDbVolume: string;
  }
> = {
  "postgresql:16": {
    image: "postgres:16-alpine",
    containerPort: 5432,
    defaultEnv: {
      POSTGRES_USER: "postgres",
      POSTGRES_PASSWORD: "POSTGRES_PASSWORD", // Triggers secret generator
    },
    defaultDbVolume: "/var/lib/postgresql/data",
  },
  "postgresql:15": {
    image: "postgres:15-alpine",
    containerPort: 5432,
    defaultEnv: {
      POSTGRES_USER: "postgres",
      POSTGRES_PASSWORD: "POSTGRES_PASSWORD", // Triggers secret generator
    },
    defaultDbVolume: "/var/lib/postgresql/data",
  },
  "redis:7": {
    image: "redis:7-alpine",
    containerPort: 6379,
    defaultEnv: {},
    defaultDbVolume: "/data",
  },
  "redis:6": {
    image: "redis:6-alpine",
    containerPort: 6379,
    defaultEnv: {},
    defaultDbVolume: "/data",
  },
  "mysql:8.0": {
    image: "mysql:8.0",
    containerPort: 3306,
    defaultEnv: {
      MYSQL_ROOT_PASSWORD: "MYSQL_ROOT_PASSWORD", // Triggers secret generator
    },
    defaultDbVolume: "/var/lib/mysql",
  },
  "mongodb:6.0": {
    image: "mongo:6.0",
    containerPort: 27017,
    defaultEnv: {},
    defaultDbVolume: "/data/db",
  },
  "nginx:1.27": {
    image: "nginx:1.27-alpine",
    containerPort: 80,
    defaultEnv: {},
    healthcheck: {
      test: ["CMD-SHELL", "curl -f http://localhost/ || exit 1"],
      interval: "10s",
      timeout: "5s",
      retries: 5,
    },
    defaultDbVolume: "/usr/share/nginx/html",
  },
};

// Resource limits mapper
const RESOURCE_LIMITS_MAP = {
  small: { cpus: "0.5", memory: "512m" },
  medium: { cpus: "1.0", memory: "1Gi" },
  large: { cpus: "2.0", memory: "2Gi" },
} as const;

// Default logging rotation
const DEFAULT_LOGGING = {
  driver: "json-file",
  options: {
    "max-size": "10m",
    "max-file": "3",
  },
};

function extractHostPort(value: string): number | null {
  const trimmed = value.trim();
  const slash = trimmed.lastIndexOf("/");
  const body = slash >= 0 ? trimmed.slice(0, slash) : trimmed;
  const parts = body.split(":");
  if (parts.length === 1) return null;
  const hostSegment = parts.length === 2 ? parts[0] : parts[parts.length - 2];
  if (hostSegment === undefined) return null;
  const match = hostSegment.match(/^(\d+)$/);
  if (!match) return null;
  return Number(match[1]);
}

async function getOccupiedPorts(ctx: ToolContext, excludeStack: string): Promise<Set<number>> {
  const occupied = new Set<number>();

  // 1. Gather from other stacks in StateStore
  const stacks = ctx.stateStore.list();
  for (const summary of stacks) {
    if (summary.name === excludeStack) continue;
    const def = ctx.stateStore.read(summary.name);
    if (!def || !def.services) continue;
    for (const spec of Object.values(def.services)) {
      for (const portVal of spec.ports ?? []) {
        const hostPort = extractHostPort(portVal);
        if (hostPort !== null) occupied.add(hostPort);
      }
    }
  }

  // 2. Gather from running containers not matching excludeStack label
  try {
    const containers = await ctx.dockerEngine.listContainers({ all: true });
    for (const c of containers) {
      if (c.State === "exited" || c.State === "dead") continue;
      if (c.Labels?.["com.docker.compose.project"] === excludeStack) continue;

      const inspected = (await ctx.dockerEngine.inspect(c.Id)) as any;
      const ports = inspected.NetworkSettings?.Ports ?? {};
      for (const bindings of Object.values(ports)) {
        if (!bindings || !Array.isArray(bindings)) continue;
        for (const b of bindings) {
          if (b.HostPort) {
            occupied.add(Number(b.HostPort));
          }
        }
      }
    }
  } catch {
    // Best-effort when docker engine is not accessible during plan
  }

  return occupied;
}

function calculateCanonicalHash(stack: Omit<PreparedStack, "hash">): string {
  const canonicalObj = {
    stackName: stack.stackName,
    intent: stack.intent,
    services: Object.keys(stack.services)
      .sort()
      .reduce((acc, key) => {
        acc[key] = stack.services[key];
        return acc;
      }, {} as any),
    networks: Object.keys(stack.networks)
      .sort()
      .reduce((acc, key) => {
        acc[key] = stack.networks[key];
        return acc;
      }, {} as any),
    volumes: Object.keys(stack.volumes)
      .sort()
      .reduce((acc, key) => {
        acc[key] = stack.volumes[key];
        return acc;
      }, {} as any),
  };
  return crypto.createHash("sha256").update(JSON.stringify(canonicalObj)).digest("hex");
}

export async function prepareStackDraft(
  input: StackDraft,
  ctx: ToolContext,
): Promise<{ ok: true; prepared: PreparedStack } | { ok: false; error: string; issues?: any[] }> {
  const services: Record<string, ServiceSpec> = {};
  const volumes: Record<string, any> = {};
  const networks: Record<string, any> = {};

  const defaultNetworkName = "default";
  networks[defaultNetworkName] = input.networkName ? { name: input.networkName } : {};

  // Fetch occupied ports on the host
  const occupiedPorts = await getOccupiedPorts(ctx, input.stackName);

  // Read the previous deployment if it exists
  const previousDef = ctx.stateStore.read(input.stackName);

  // Auto port allocation range
  let nextAutoPort = 8000;

  for (const intent of input.services) {
    const serviceName = intent.name;
    const spec: ServiceSpec = {
      image: "",
      environment: intent.environment ?? {},
      networks: [defaultNetworkName],
      logging: DEFAULT_LOGGING,
    };

    if (intent.depends_on) {
      spec.depends_on = intent.depends_on;
    }

    if (intent.command) {
      spec.command = intent.command;
    }

    if (intent.scale) {
      spec.scale = intent.scale;
    }

    if (intent.configMounts) {
      spec.volumes = spec.volumes ?? [];
      for (const mount of intent.configMounts) {
        spec.volumes.push(`${mount.hostPath}:${mount.containerPath}`);
      }
    }

    // 1. Kind specific mapping
    if (intent.kind === "catalog") {
      const catalogEntry = CATALOG_REGISTRY[intent.catalogId ?? ""];
      if (!catalogEntry) {
        return {
          ok: false,
          error: `Catalog entry not found for catalogId: ${intent.catalogId}`,
        };
      }

      spec.image = catalogEntry.image;
      spec.environment = { ...catalogEntry.defaultEnv, ...spec.environment };
      spec.healthcheck = catalogEntry.healthcheck;

      if (intent.persistence) {
        const volName = `${serviceName}_data`;
        spec.volumes = [`${volName}:${catalogEntry.defaultDbVolume}`];
        volumes[volName] = {};
      }
    } else {
      // Custom Service
      if (!intent.image) {
        return {
          ok: false,
          error: `Image must be specified for custom service: ${serviceName}`,
        };
      }
      spec.image = intent.image;

      if (intent.persistence) {
        const mountPath = intent.persistence.path ?? "/data";
        const volName = `${serviceName}_data`;
        spec.volumes = [`${volName}:${mountPath}`];
        volumes[volName] = {};
      }
    }

    // 2. Resource mapping
    if (intent.resources) {
      const limits = RESOURCE_LIMITS_MAP[intent.resources];
      if (limits) {
        spec.deploy = {
          resources: {
            limits,
          },
        };
      }
    }

    // 3. Port mapping and deterministic allocation
    if (intent.exposure === "public") {
      let containerPort = 80;
      if (intent.kind === "catalog") {
        const catalogEntry = CATALOG_REGISTRY[intent.catalogId ?? ""];
        if (catalogEntry) containerPort = catalogEntry.containerPort;
      } else if (intent.containerPort) {
        containerPort = intent.containerPort;
      }

      let hostPort: number | null = null;

      // Rule A: Honor explicit developer-specified hostPort
      if (intent.hostPort) {
        hostPort = intent.hostPort;
      }

      // Rule B: Re-use previously allocated hostPort for this service from the StateStore
      // Rule B: Re-use previously allocated hostPort for this service from the StateStore
      if (!hostPort && previousDef && previousDef.services?.[serviceName]) {
        const prevPorts = previousDef.services[serviceName].ports ?? [];
        const firstPort = prevPorts[0];
        if (firstPort) {
          const prevHostPort = extractHostPort(firstPort);
          if (prevHostPort !== null) {
            hostPort = prevHostPort;
          }
        }
      }

      // Rule C: Auto-allocate first-free port in the 8000-9000 range
      if (!hostPort) {
        while (nextAutoPort <= 9000) {
          if (!occupiedPorts.has(nextAutoPort)) {
            hostPort = nextAutoPort;
            occupiedPorts.add(nextAutoPort); // Mark as occupied for subsequent services
            break;
          }
          nextAutoPort++;
        }
      }

      if (!hostPort) {
        return {
          ok: false,
          error: `Could not allocate a free host port in the 8000-9000 range for service '${serviceName}'`,
        };
      }

      spec.ports = [`${hostPort}:${containerPort}`];
    }

    services[serviceName] = spec;
  }

  injectDbHealthchecks(services);

  const prepared: any = {
    stackName: input.stackName,
    intent: input.intent,
    services,
    networks,
    volumes,
  };
  if (input.configFiles !== undefined) {
    prepared.configFiles = input.configFiles;
  }

  const hash = calculateCanonicalHash(prepared);

  return {
    ok: true,
    prepared: {
      ...prepared,
      hash,
    },
  };
}
