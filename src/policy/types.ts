export interface ResourceLimitsConfig {
  cpuRequired?: boolean;
  memoryRequired?: boolean;
  maxMemory?: string; // e.g. "4GiB", "512m", "1024k"
}

export interface LoggingRotationConfig {
  maxSize?: string; // e.g. "20m"
  maxFiles?: number;
}

export interface HealthcheckConfig {
  required?: boolean;
  maxIntervalSeconds?: number;
  maxTimeoutSeconds?: number;
}

export interface UntrustedRegistryConfig {
  allowedRegistries?: string[];
}

export type DenyRuleConfig =
  | string
  | { untrusted_registry: UntrustedRegistryConfig };

export type RequireRuleConfig =
  | string
  | { resource_limits: ResourceLimitsConfig }
  | { logging_rotation: LoggingRotationConfig }
  | { healthcheck: HealthcheckConfig };

export interface PolicyGroup {
  hardDeny?: DenyRuleConfig[];
  require?: RequireRuleConfig[];
}

export interface PolicyConfig {
  schemaVersion?: string;
  global?: PolicyGroup;
  project?: PolicyGroup;
}

export interface PolicyViolation {
  service: string;
  rule: string;
  message: string;
  severity: "deny" | "warn";
}
