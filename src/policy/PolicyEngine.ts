import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import * as yaml from "yaml";
import type { UserConfig } from "../config";
import type {
  DenyRuleConfig,
  HealthcheckConfig,
  LoggingRotationConfig,
  PolicyConfig,
  PolicyGroup,
  PolicyViolation,
  RequireRuleConfig,
  ResourceLimitsConfig,
  UntrustedRegistryConfig,
} from "./types";

export function parseSizeToBytes(sizeStr: string): number {
  const match = sizeStr.trim().match(/^(\d+(?:\.\d+)?)\s*([a-zA-Z]*)$/);
  if (!match) throw new Error(`Invalid size format: ${sizeStr}`);
  const value = parseFloat(match[1]);
  const unit = match[2].toLowerCase();
  switch (unit) {
    case "":
    case "b":
      return value;
    case "k":
    case "kb":
    case "ki":
    case "kib":
      return value * 1024;
    case "m":
    case "mb":
    case "mi":
    case "mib":
      return value * 1024 * 1024;
    case "g":
    case "gb":
    case "gi":
    case "gib":
      return value * 1024 * 1024 * 1024;
    default:
      throw new Error(`Unknown size unit: ${unit}`);
  }
}

export class PolicyEngine {
  private globalPolicy: PolicyGroup = {};
  private projectPolicy: PolicyGroup = {};
  private hasProjectPolicy = false;
  private missingProjectPolicyMode: "use-global" | "deny" = "deny";

  constructor(options?: {
    globalPolicyPath?: string;
    projectPolicyPath?: string;
    userConfig?: UserConfig;
  }) {
    const globalPath =
      options?.globalPolicyPath ??
      path.join(os.homedir(), ".docker-agent", "policies.yaml");
    const projectPath =
      options?.projectPolicyPath ??
      path.join(process.cwd(), ".docker-agent", "policies.yaml");

    this.missingProjectPolicyMode =
      options?.userConfig?.defaults?.missingProjectPolicy ?? "deny";

    this.loadPolicies(globalPath, projectPath);
  }

  private loadPolicies(globalPath: string, projectPath: string) {
    // 1. Load global policy
    if (fs.existsSync(globalPath)) {
      try {
        const content = fs.readFileSync(globalPath, "utf-8");
        const parsed = yaml.parse(content) as PolicyConfig;
        if (parsed?.global) {
          this.globalPolicy = parsed.global;
        }
      } catch (err) {
        throw new Error(
          `Failed to parse global policy file: ${(err as Error).message}`,
        );
      }
    }

    // 2. Load project policy
    if (fs.existsSync(projectPath)) {
      try {
        const content = fs.readFileSync(projectPath, "utf-8");
        const parsed = yaml.parse(content) as PolicyConfig;
        if (parsed?.project) {
          this.projectPolicy = parsed.project;
          this.hasProjectPolicy = true;
        }
      } catch (err) {
        throw new Error(
          `Failed to parse project policy file: ${(err as Error).message}`,
        );
      }
    } else {
      this.hasProjectPolicy = false;
    }

    // 3. Validate that project policy does not loosen global policy
    this.validatePolicyHierarchy();
  }

  private validatePolicyHierarchy() {
    if (!this.hasProjectPolicy) return;

    // A helper to extract rule names
    const getRuleName = (rule: DenyRuleConfig | RequireRuleConfig): string => {
      if (typeof rule === "string") return rule;
      return Object.keys(rule)[0];
    };

    // Ensure project does not loosen global resource_limits
    const globalLimits = this.findRequireRule<ResourceLimitsConfig>(
      this.globalPolicy,
      "resource_limits",
    );
    const projectLimits = this.findRequireRule<ResourceLimitsConfig>(
      this.projectPolicy,
      "resource_limits",
    );
    if (globalLimits && projectLimits) {
      if (globalLimits.cpuRequired && projectLimits.cpuRequired === false) {
        throw new Error(
          "Invalid policy configuration: Project policy cannot disable cpuRequired if enabled globally",
        );
      }
      if (globalLimits.memoryRequired && projectLimits.memoryRequired === false) {
        throw new Error(
          "Invalid policy configuration: Project policy cannot disable memoryRequired if enabled globally",
        );
      }
      if (globalLimits.maxMemory && projectLimits.maxMemory) {
        const globalBytes = parseSizeToBytes(globalLimits.maxMemory);
        const projectBytes = parseSizeToBytes(projectLimits.maxMemory);
        if (projectBytes > globalBytes) {
          throw new Error(
            `Invalid policy configuration: Project maxMemory (${projectLimits.maxMemory}) cannot exceed Global maxMemory (${globalLimits.maxMemory})`,
          );
        }
      }
    }

    // Ensure project does not loosen global logging_rotation
    const globalLog = this.findRequireRule<LoggingRotationConfig>(
      this.globalPolicy,
      "logging_rotation",
    );
    const projectLog = this.findRequireRule<LoggingRotationConfig>(
      this.projectPolicy,
      "logging_rotation",
    );
    if (globalLog && projectLog) {
      if (globalLog.maxSize && projectLog.maxSize) {
        const globalBytes = parseSizeToBytes(globalLog.maxSize);
        const projectBytes = parseSizeToBytes(projectLog.maxSize);
        if (projectBytes > globalBytes) {
          throw new Error(
            `Invalid policy configuration: Project maxSize (${projectLog.maxSize}) cannot exceed Global maxSize (${globalLog.maxSize})`,
          );
        }
      }
      if (
        globalLog.maxFiles !== undefined &&
        projectLog.maxFiles !== undefined
      ) {
        if (projectLog.maxFiles > globalLog.maxFiles) {
          throw new Error(
            `Invalid policy configuration: Project maxFiles (${projectLog.maxFiles}) cannot exceed Global maxFiles (${globalLog.maxFiles})`,
          );
        }
      }
    }

    // Ensure project does not loosen global healthcheck
    const globalHealth = this.findRequireRule<HealthcheckConfig>(
      this.globalPolicy,
      "healthcheck",
    );
    const projectHealth = this.findRequireRule<HealthcheckConfig>(
      this.projectPolicy,
      "healthcheck",
    );
    if (globalHealth && projectHealth) {
      if (globalHealth.required && projectHealth.required === false) {
        throw new Error(
          "Invalid policy configuration: Project policy cannot disable healthcheck required if enabled globally",
        );
      }
      if (
        globalHealth.maxIntervalSeconds !== undefined &&
        projectHealth.maxIntervalSeconds !== undefined
      ) {
        if (projectHealth.maxIntervalSeconds > globalHealth.maxIntervalSeconds) {
          throw new Error(
            `Invalid policy configuration: Project maxIntervalSeconds (${projectHealth.maxIntervalSeconds}) cannot exceed Global maxIntervalSeconds (${globalHealth.maxIntervalSeconds})`,
          );
        }
      }
      if (
        globalHealth.maxTimeoutSeconds !== undefined &&
        projectHealth.maxTimeoutSeconds !== undefined
      ) {
        if (projectHealth.maxTimeoutSeconds > globalHealth.maxTimeoutSeconds) {
          throw new Error(
            `Invalid policy configuration: Project maxTimeoutSeconds (${projectHealth.maxTimeoutSeconds}) cannot exceed Global maxTimeoutSeconds (${globalHealth.maxTimeoutSeconds})`,
          );
        }
      }
    }

    // Ensure project registry whitelist is a subset of global registry whitelist
    const globalReg = this.findDenyRule<UntrustedRegistryConfig>(
      this.globalPolicy,
      "untrusted_registry",
    );
    const projectReg = this.findDenyRule<UntrustedRegistryConfig>(
      this.projectPolicy,
      "untrusted_registry",
    );
    if (globalReg?.allowedRegistries && projectReg?.allowedRegistries) {
      const globalSet = new Set(globalReg.allowedRegistries);
      for (const reg of projectReg.allowedRegistries) {
        if (!globalSet.has(reg)) {
          throw new Error(
            `Invalid policy configuration: Project registry whitelist allows registry '${reg}' which is not in Global registry whitelist`,
          );
        }
      }
    }
  }

  private findRequireRule<T>(
    group: PolicyGroup,
    ruleName: string,
  ): T | undefined {
    if (!group.require) return undefined;
    for (const rule of group.require) {
      if (typeof rule !== "string" && ruleName in rule) {
        return (rule as Record<string, T>)[ruleName];
      }
    }
    return undefined;
  }

  private findDenyRule<T>(group: PolicyGroup, ruleName: string): T | undefined {
    if (!group.hardDeny) return undefined;
    for (const rule of group.hardDeny) {
      if (typeof rule !== "string" && ruleName in rule) {
        return (rule as Record<string, T>)[ruleName];
      }
    }
    return undefined;
  }

  public getEffectivePolicy(): {
    hardDeny: Set<string>;
    require: Set<string>;
    untrustedRegistry?: UntrustedRegistryConfig;
    resourceLimits?: ResourceLimitsConfig;
    loggingRotation?: LoggingRotationConfig;
    healthcheck?: HealthcheckConfig;
  } {
    const hardDeny = new Set<string>();
    const require = new Set<string>();

    let untrustedRegistry: UntrustedRegistryConfig | undefined = undefined;
    let resourceLimits: ResourceLimitsConfig | undefined = undefined;
    let loggingRotation: LoggingRotationConfig | undefined = undefined;
    let healthcheck: HealthcheckConfig | undefined = undefined;

    const processDenyRule = (rule: DenyRuleConfig) => {
      if (typeof rule === "string") {
        hardDeny.add(rule);
      } else if ("untrusted_registry" in rule) {
        hardDeny.add("untrusted_registry");
        // Merging: union of allowed, but project must be a subset of global.
        // If both exist, project rules are tighter, so use project allowedRegistries.
        // If only global exists, use global. If only project exists, use project.
        const projectReg = rule.untrusted_registry;
        const globalReg = this.findDenyRule<UntrustedRegistryConfig>(
          this.globalPolicy,
          "untrusted_registry",
        );
        if (projectReg && globalReg) {
          untrustedRegistry = projectReg;
        } else {
          untrustedRegistry = projectReg || globalReg;
        }
      }
    };

    const processRequireRule = (rule: RequireRuleConfig) => {
      if (typeof rule === "string") {
        require.add(rule);
      } else {
        const key = Object.keys(rule)[0];
        require.add(key);
        if ("resource_limits" in rule) {
          const projectLimits = rule.resource_limits;
          const globalLimits = this.findRequireRule<ResourceLimitsConfig>(
            this.globalPolicy,
            "resource_limits",
          );
          if (projectLimits && globalLimits) {
            // merge limits, project overriding and making tighter
            resourceLimits = {
              cpuRequired: globalLimits.cpuRequired || projectLimits.cpuRequired,
              memoryRequired:
                globalLimits.memoryRequired || projectLimits.memoryRequired,
              maxMemory: projectLimits.maxMemory || globalLimits.maxMemory,
            };
          } else {
            resourceLimits = projectLimits || globalLimits;
          }
        } else if ("logging_rotation" in rule) {
          const projectLog = rule.logging_rotation;
          const globalLog = this.findRequireRule<LoggingRotationConfig>(
            this.globalPolicy,
            "logging_rotation",
          );
          if (projectLog && globalLog) {
            loggingRotation = {
              maxSize: projectLog.maxSize || globalLog.maxSize,
              maxFiles:
                projectLog.maxFiles !== undefined
                  ? projectLog.maxFiles
                  : globalLog.maxFiles,
            };
          } else {
            loggingRotation = projectLog || globalLog;
          }
        } else if ("healthcheck" in rule) {
          const projectHealth = rule.healthcheck;
          const globalHealth = this.findRequireRule<HealthcheckConfig>(
            this.globalPolicy,
            "healthcheck",
          );
          if (projectHealth && globalHealth) {
            healthcheck = {
              required: globalHealth.required || projectHealth.required,
              maxIntervalSeconds:
                projectHealth.maxIntervalSeconds !== undefined
                  ? projectHealth.maxIntervalSeconds
                  : globalHealth.maxIntervalSeconds,
              maxTimeoutSeconds:
                projectHealth.maxTimeoutSeconds !== undefined
                  ? projectHealth.maxTimeoutSeconds
                  : globalHealth.maxTimeoutSeconds,
            };
          } else {
            healthcheck = projectHealth || globalHealth;
          }
        }
      }
    };

    // 1. Process global
    if (this.globalPolicy.hardDeny) {
      for (const rule of this.globalPolicy.hardDeny) processDenyRule(rule);
    }
    if (this.globalPolicy.require) {
      for (const rule of this.globalPolicy.require) processRequireRule(rule);
    }

    // 2. Process project
    if (this.projectPolicy.hardDeny) {
      for (const rule of this.projectPolicy.hardDeny) processDenyRule(rule);
    }
    if (this.projectPolicy.require) {
      for (const rule of this.projectPolicy.require) processRequireRule(rule);
    }

    return {
      hardDeny,
      require,
      untrustedRegistry,
      resourceLimits,
      loggingRotation,
      healthcheck,
    };
  }

  public evaluate(composeYaml: string): PolicyViolation[] {
    const violations: PolicyViolation[] = [];

    // Check project policy presence
    if (!this.hasProjectPolicy) {
      if (this.missingProjectPolicyMode === "deny") {
        violations.push({
          service: "*",
          rule: "project_policy_missing",
          message: "Project policy not found. Deployment is denied.",
          severity: "deny",
        });
        return violations;
      }
    }

    let doc: any;
    try {
      doc = yaml.parse(composeYaml);
    } catch (err) {
      violations.push({
        service: "*",
        rule: "invalid_yaml",
        message: `Failed to parse Compose YAML: ${(err as Error).message}`,
        severity: "deny",
      });
      return violations;
    }

    if (!doc || typeof doc !== "object" || !doc.services) {
      return violations;
    }

    const effective = this.getEffectivePolicy();
    const services = Object.entries(doc.services) as [string, any][];

    for (const [name, svc] of services) {
      if (!svc || typeof svc !== "object") continue;

      // --- DENY RULES ---
      if (effective.hardDeny.has("privileged_containers")) {
        if (svc.privileged === true) {
          violations.push({
            service: name,
            rule: "privileged_containers",
            message: "Privileged container is not allowed",
            severity: "deny",
          });
        }
      }

      if (effective.hardDeny.has("mount_docker_socket")) {
        const volumes = (svc.volumes || []) as (string | any)[];
        for (const vol of volumes) {
          const hostPath = typeof vol === "string" ? vol.split(":")[0] : vol.source;
          if (hostPath === "/var/run/docker.sock") {
            violations.push({
              service: name,
              rule: "mount_docker_socket",
              message: "Mounting docker socket (/var/run/docker.sock) is not allowed",
              severity: "deny",
            });
          }
        }
      }

      if (effective.hardDeny.has("mount_host_root")) {
        const volumes = (svc.volumes || []) as (string | any)[];
        const forbiddenRoots = ["/", "/etc", "/root", "/usr", "/var"].map((p) =>
          path.normalize(p).replace(/\\/g, "/"),
        );
        for (const vol of volumes) {
          const hostPath = typeof vol === "string" ? vol.split(":")[0] : vol.source;
          if (hostPath) {
            const normalizedHostPath = path.normalize(hostPath).replace(/\\/g, "/");
            if (forbiddenRoots.includes(normalizedHostPath)) {
              violations.push({
                service: name,
                rule: "mount_host_root",
                message: `Mounting host root or system directory (${hostPath}) is not allowed`,
                severity: "deny",
              });
            }
          }
        }
      }

      if (effective.hardDeny.has("host_pid_namespace")) {
        if (svc.pid === "host") {
          violations.push({
            service: name,
            rule: "host_pid_namespace",
            message: "Host PID namespace configuration is not allowed",
            severity: "deny",
          });
        }
      }

      if (effective.hardDeny.has("host_network")) {
        if (svc.network_mode === "host") {
          violations.push({
            service: name,
            rule: "host_network",
            message: "Host network mode is not allowed",
            severity: "deny",
          });
        }
      }

      if (effective.hardDeny.has("add_all_linux_capabilities")) {
        const capAdd = (svc.cap_add || []) as string[];
        if (capAdd.includes("ALL") || capAdd.includes("all")) {
          violations.push({
            service: name,
            rule: "add_all_linux_capabilities",
            message: "Adding ALL Linux capabilities is not allowed",
            severity: "deny",
          });
        }
      }

      if (effective.hardDeny.has("disable_seccomp")) {
        const securityOpt = (svc.security_opt || []) as string[];
        for (const opt of securityOpt) {
          if (opt.toLowerCase().replace(/\s/g, "") === "seccomp:unconfined") {
            violations.push({
              service: name,
              rule: "disable_seccomp",
              message: "Disabling seccomp (seccomp:unconfined) is not allowed",
              severity: "deny",
            });
          }
        }
      }

      if (effective.hardDeny.has("untrusted_registry") && effective.untrustedRegistry) {
        const image = (svc.image || "") as string;
        if (image) {
          const allowed = effective.untrustedRegistry.allowedRegistries || [];
          const registry = this.extractRegistry(image);
          if (!allowed.includes(registry)) {
            violations.push({
              service: name,
              rule: "untrusted_registry",
              message: `Image uses untrusted registry '${registry}'. Allowed registries: ${allowed.join(", ")}`,
              severity: "deny",
            });
          }
        }
      }

      if (effective.hardDeny.has("expose_database_publicly")) {
        const image = (svc.image || "") as string;
        if (this.isDatabaseImage(image)) {
          const ports = (svc.ports || []) as (string | any)[];
          for (const port of ports) {
            const portStr = typeof port === "string" ? port : `${port.published}:${port.target}`;
            // If port is exposed publicly e.g. "5432:5432" or "0.0.0.0:5432:5432" (default host IP is 0.0.0.0)
            if (!portStr.startsWith("127.0.0.1:") && !portStr.startsWith("localhost:")) {
              violations.push({
                service: name,
                rule: "expose_database_publicly",
                message: `Exposing database port (${portStr}) publicly is not allowed. Expose it to 127.0.0.1 or keep it within the container network.`,
                severity: "deny",
              });
            }
          }
        }
      }

      // --- REQUIRE RULES ---
      if (effective.require.has("restart_policy")) {
        if (!svc.restart || svc.restart === "no") {
          violations.push({
            service: name,
            rule: "restart_policy",
            message: "A restart policy (other than 'no') must be configured",
            severity: "deny",
          });
        }
      }

      if (effective.require.has("resource_limits") && effective.resourceLimits) {
        const limits = svc.deploy?.resources?.limits;
        const conf = effective.resourceLimits;
        if (conf.cpuRequired && !limits?.cpus) {
          violations.push({
            service: name,
            rule: "resource_limits",
            message: "CPU limits are required",
            severity: "deny",
          });
        }
        if (conf.memoryRequired && !limits?.memory) {
          violations.push({
            service: name,
            rule: "resource_limits",
            message: "Memory limits are required",
            severity: "deny",
          });
        }
        if (conf.maxMemory && limits?.memory) {
          const maxBytes = parseSizeToBytes(conf.maxMemory);
          const currentBytes = parseSizeToBytes(limits.memory);
          if (currentBytes > maxBytes) {
            violations.push({
              service: name,
              rule: "resource_limits",
              message: `Memory limit (${limits.memory}) exceeds maximum allowed limit (${conf.maxMemory})`,
              severity: "deny",
            });
          }
        }
      }

      if (effective.require.has("logging_rotation") && effective.loggingRotation) {
        const logConfig = svc.logging;
        const conf = effective.loggingRotation;
        if (!logConfig || logConfig.driver !== "json-file") {
          violations.push({
            service: name,
            rule: "logging_rotation",
            message: "Logging driver 'json-file' must be configured for log rotation",
            severity: "deny",
          });
        } else {
          const maxS = logConfig.options?.["max-size"];
          const maxF = logConfig.options?.["max-file"];
          if (conf.maxSize && (!maxS || parseSizeToBytes(maxS) > parseSizeToBytes(conf.maxSize))) {
            violations.push({
              service: name,
              rule: "logging_rotation",
              message: `Log max-size (${maxS || "unlimited"}) is missing or exceeds allowed size (${conf.maxSize})`,
              severity: "deny",
            });
          }
          if (conf.maxFiles !== undefined && (!maxF || parseInt(maxF, 10) > conf.maxFiles)) {
            violations.push({
              service: name,
              rule: "logging_rotation",
              message: `Log max-file (${maxF || "unlimited"}) is missing or exceeds allowed files (${conf.maxFiles})`,
              severity: "deny",
            });
          }
        }
      }

      if (effective.require.has("healthcheck") && effective.healthcheck) {
        const hc = svc.healthcheck;
        const conf = effective.healthcheck;
        if (conf.required && (!hc || !hc.test || hc.disable === true)) {
          violations.push({
            service: name,
            rule: "healthcheck",
            message: "Healthcheck is required",
            severity: "deny",
          });
        } else if (hc && hc.disable !== true) {
          if (conf.maxIntervalSeconds !== undefined && hc.interval) {
            const intervalSec = this.parseDurationToSeconds(hc.interval);
            if (intervalSec > conf.maxIntervalSeconds) {
              violations.push({
                service: name,
                rule: "healthcheck",
                message: `Healthcheck interval (${hc.interval}) exceeds maximum interval (${conf.maxIntervalSeconds}s)`,
                severity: "deny",
              });
            }
          }
          if (conf.maxTimeoutSeconds !== undefined && hc.timeout) {
            const timeoutSec = this.parseDurationToSeconds(hc.timeout);
            if (timeoutSec > conf.maxTimeoutSeconds) {
              violations.push({
                service: name,
                rule: "healthcheck",
                message: `Healthcheck timeout (${hc.timeout}) exceeds maximum timeout (${conf.maxTimeoutSeconds}s)`,
                severity: "deny",
              });
            }
          }
        }
      }

      if (effective.require.has("non_root_user")) {
        if (!svc.user) {
          violations.push({
            service: name,
            rule: "non_root_user",
            message: "Running as non-root user (e.g., user: '1000:1000') is required",
            severity: "deny",
          });
        }
      }

      if (effective.require.has("read_only_root_filesystem_when_possible")) {
        if (svc.read_only !== true) {
          violations.push({
            service: name,
            rule: "read_only_root_filesystem_when_possible",
            message: "Read-only root filesystem is recommended (read_only: true)",
            severity: "warn",
          });
        }
      }

      if (effective.require.has("project_labels")) {
        if (!svc.labels) {
          violations.push({
            service: name,
            rule: "project_labels",
            message: "Project labels are required",
            severity: "deny",
          });
        }
      }
    }

    return violations;
  }

  private extractRegistry(image: string): string {
    const parts = image.split("/");
    if (parts.length > 1 && (parts[0].includes(".") || parts[0].includes(":") || parts[0] === "localhost")) {
      return parts[0];
    }
    return "docker.io";
  }

  private isDatabaseImage(image: string): boolean {
    const dbImages = ["postgres", "mysql", "mariadb", "redis", "mongo", "elasticsearch", "clickhouse"];
    const imageName = image.split("/").pop()?.split(":")[0] || "";
    return dbImages.some((db) => imageName.includes(db));
  }

  private parseDurationToSeconds(durationStr: string): number {
    const match = durationStr.trim().match(/^(\d+(?:\.\d+)?)\s*(s|m|h)?$/);
    if (!match) throw new Error(`Invalid duration format: ${durationStr}`);
    const value = parseFloat(match[1]);
    const unit = match[2] || "s";
    switch (unit) {
      case "s":
        return value;
      case "m":
        return value * 60;
      case "h":
        return value * 3600;
      default:
        return value;
    }
  }
}
