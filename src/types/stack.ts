export interface ServiceSpec {
  image: string;
  command?: string | string[];
  ports?: string[];
  environment?: Record<string, string>;
  env_file?: string[];
  volumes?: string[];
  depends_on?:
    | string[]
    | Record<
        string,
        { condition: "service_started" | "service_healthy" | "service_completed_successfully" }
      >;
  healthcheck?: {
    test: string | string[];
    interval?: string;
    timeout?: string;
    retries?: number;
    start_period?: string;
  };
  restart?: "no" | "always" | "on-failure" | "unless-stopped";
  labels?: Record<string, string>;
  networks?: string[];
  scale?: number;
}

export interface EnvFileSource {
  generated: boolean;
  path: string;
  addedKeys?: string[];
}

export interface DockerAgentMeta {
  name: string;
  createdAt: string;
  lastApplied: string | null;
  intent: string;
  provider: string;
  generatedBy: string;
  envFileSources: Record<string, EnvFileSource>;
}

export interface StackDefinition {
  "x-docker-agent": DockerAgentMeta;
  services: Record<string, ServiceSpec>;
  networks?: Record<string, unknown>;
  volumes?: Record<string, unknown>;
}

export interface StackSummary {
  name: string;
  serviceCount: number;
  lastApplied: string | null;
}

export interface ServiceSnapshot {
  image: string;
  command: string | string[] | null;
  ports: string[];
  env: EnvSnapshot;
  volumes: string[];
  replicaCount: number;
  state?: string;
}

export interface EnvSnapshot {
  visible: Record<string, string>;
  secretKeys: string[];
  secretHashesByKey: Record<string, string>;
}

export interface ServiceDiff {
  service: string;
  desired: ServiceSnapshot | null;
  actual: ServiceSnapshot | null;
  changes: Array<{ field: string; from: unknown; to: unknown }>;
}

export interface StackDiff {
  stackName: string;
  status: "in_sync" | "drift" | "missing" | "extra";
  serviceDiffs: ServiceDiff[];
}
