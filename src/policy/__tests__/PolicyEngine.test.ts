import * as fs from "node:fs";
import * as path from "node:path";
import { afterAll, beforeAll, describe, expect, test } from "vitest";
import { PolicyEngine, parseSizeToBytes } from "../PolicyEngine";

const TEST_DIR = path.join(process.cwd(), ".docker-agent-test", "temp-policy-test");

describe("PolicyEngine and helper tests", () => {
  beforeAll(() => {
    fs.mkdirSync(TEST_DIR, { recursive: true });
  });

  afterAll(() => {
    try {
      fs.rmSync(TEST_DIR, { recursive: true, force: true });
    } catch {
      // ignore
    }
  });

  describe("parseSizeToBytes helper", () => {
    test("parses basic sizes without unit", () => {
      expect(parseSizeToBytes("100")).toBe(100);
      expect(parseSizeToBytes("10.5")).toBe(10.5);
    });

    test("parses sizes with units (case-insensitive, optional spaces)", () => {
      expect(parseSizeToBytes("10k")).toBe(10 * 1024);
      expect(parseSizeToBytes("1.5 kb")).toBe(1.5 * 1024);
      expect(parseSizeToBytes("20M")).toBe(20 * 1024 * 1024);
      expect(parseSizeToBytes("4GiB")).toBe(4 * 1024 * 1024 * 1024);
    });

    test("throws on invalid format", () => {
      expect(() => parseSizeToBytes("abc")).toThrow();
      expect(() => parseSizeToBytes("10xyz")).toThrow();
    });
  });

  describe("Policy Merging and Validation", () => {
    const globalPath = path.join(TEST_DIR, "global-policies.yaml");
    const projectPath = path.join(TEST_DIR, "project-policies.yaml");

    test("merges global and project rules correctly", () => {
      fs.writeFileSync(
        globalPath,
        `
global:
  hardDeny:
    - mount_docker_socket
  require:
    - restart_policy
        `,
      );

      fs.writeFileSync(
        projectPath,
        `
project:
  hardDeny:
    - privileged_containers
  require:
    - non_root_user
        `,
      );

      const engine = new PolicyEngine({
        globalPolicyPath: globalPath,
        projectPolicyPath: projectPath,
      });

      const effective = engine.getEffectivePolicy();
      expect(effective.hardDeny.has("mount_docker_socket")).toBe(true);
      expect(effective.hardDeny.has("privileged_containers")).toBe(true);
      expect(effective.require.has("restart_policy")).toBe(true);
      expect(effective.require.has("non_root_user")).toBe(true);
    });

    test("throws error if project policy loosens global resource limits", () => {
      fs.writeFileSync(
        globalPath,
        `
global:
  require:
    - resource_limits:
        cpuRequired: true
        maxMemory: 4GiB
        `,
      );

      fs.writeFileSync(
        projectPath,
        `
project:
  require:
    - resource_limits:
        cpuRequired: false
        `,
      );

      expect(
        () =>
          new PolicyEngine({
            globalPolicyPath: globalPath,
            projectPolicyPath: projectPath,
          }),
      ).toThrow("Project policy cannot disable cpuRequired if enabled globally");

      // Test memory limit loosening
      fs.writeFileSync(
        projectPath,
        `
project:
  require:
    - resource_limits:
        maxMemory: 8GiB
        `,
      );

      expect(
        () =>
          new PolicyEngine({
            globalPolicyPath: globalPath,
            projectPolicyPath: projectPath,
          }),
      ).toThrow("Project maxMemory (8GiB) cannot exceed Global maxMemory (4GiB)");
    });

    test("throws error if project registry whitelist allows untrusted registry", () => {
      fs.writeFileSync(
        globalPath,
        `
global:
  hardDeny:
    - untrusted_registry:
        allowedRegistries:
          - docker.io
          - gcr.io
        `,
      );

      fs.writeFileSync(
        projectPath,
        `
project:
  hardDeny:
    - untrusted_registry:
        allowedRegistries:
          - docker.io
          - untrusted.com
        `,
      );

      expect(
        () =>
          new PolicyEngine({
            globalPolicyPath: globalPath,
            projectPolicyPath: projectPath,
          }),
      ).toThrow("Project registry whitelist allows registry 'untrusted.com' which is not in Global registry whitelist");
    });
  });

  describe("YAML Evaluation", () => {
    const globalPath = path.join(TEST_DIR, "global-policies.yaml");
    const projectPath = path.join(TEST_DIR, "project-policies.yaml");

    test("denies deployment if project policy is missing and mode is deny", () => {
      fs.writeFileSync(globalPath, "global: {}");
      if (fs.existsSync(projectPath)) fs.unlinkSync(projectPath);

      const engine = new PolicyEngine({
        globalPolicyPath: globalPath,
        projectPolicyPath: projectPath,
        userConfig: {
          provider: "gemini",
          model: undefined,
          defaults: { autoApproveNonDestructive: false, missingProjectPolicy: "deny" },
        },
      });

      const violations = engine.evaluate("version: '3'\nservices:\n  app:\n    image: nginx");
      expect(violations.length).toBe(1);
      expect(violations[0]?.rule).toBe("project_policy_missing");
    });

    test("allows deployment with only global policy if missingProjectPolicy is use-global", () => {
      fs.writeFileSync(
        globalPath,
        `
global:
  hardDeny:
    - mount_docker_socket
        `,
      );
      if (fs.existsSync(projectPath)) fs.unlinkSync(projectPath);

      const engine = new PolicyEngine({
        globalPolicyPath: globalPath,
        projectPolicyPath: projectPath,
        userConfig: {
          provider: "gemini",
          model: undefined,
          defaults: { autoApproveNonDestructive: false, missingProjectPolicy: "use-global" },
        },
      });

      // Valid YAML
      let violations = engine.evaluate(`
services:
  app:
    image: nginx
      `);
      expect(violations.length).toBe(0);

      // Violating YAML (mount docker socket)
      violations = engine.evaluate(`
services:
  app:
    image: nginx
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      `);
      expect(violations.length).toBe(1);
      expect(violations[0]?.rule).toBe("mount_docker_socket");
    });

    test("checks hardDeny and require rules successfully", () => {
      fs.writeFileSync(
        globalPath,
        `
global:
  hardDeny:
    - privileged_containers
    - host_pid_namespace
    - host_network
    - add_all_linux_capabilities
    - disable_seccomp
    - untrusted_registry:
        allowedRegistries:
          - docker.io
    - expose_database_publicly
  require:
    - restart_policy
    - non_root_user
    - read_only_root_filesystem_when_possible
    - project_labels
    - resource_limits:
        cpuRequired: true
        memoryRequired: true
        maxMemory: 2GiB
    - logging_rotation:
        maxSize: 10m
        maxFiles: 3
    - healthcheck:
        required: true
        maxIntervalSeconds: 30
        maxTimeoutSeconds: 5
        `,
      );

      fs.writeFileSync(
        projectPath,
        `
project:
  hardDeny:
    - mount_docker_socket
    - mount_host_root
        `,
      );

      const engine = new PolicyEngine({
        globalPolicyPath: globalPath,
        projectPolicyPath: projectPath,
      });

      // A composite bad YAML violating almost all rules
      const badYaml = `
services:
  db:
    image: postgres:latest
    privileged: true
    pid: host
    network_mode: host
    cap_add:
      - ALL
    security_opt:
      - seccomp:unconfined
    ports:
      - "5432:5432"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc:/etc
    # missing user (runs as root)
    # missing restart
    # missing read_only
    # missing labels
    # missing resource limits
    # missing logging rotation
    # missing healthcheck
  
  web:
    image: customreg.com/nginx:latest # untrusted registry
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 4GiB # exceeds maxMemory 2GiB
    logging:
      driver: json-file
      options:
        max-size: 20m # exceeds max-size 10m
        max-file: '5' # exceeds max-file 3
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost"]
      interval: 1m # exceeds maxIntervalSeconds 30s
      timeout: 10s # exceeds maxTimeoutSeconds 5s
      `;

      const violations = engine.evaluate(badYaml);

      // Verify specific violations are found
      const dbViolations = violations.filter((v) => v.service === "db");
      const webViolations = violations.filter((v) => v.service === "web");

      expect(dbViolations.some((v) => v.rule === "privileged_containers")).toBe(true);
      expect(dbViolations.some((v) => v.rule === "host_pid_namespace")).toBe(true);
      expect(dbViolations.some((v) => v.rule === "host_network")).toBe(true);
      expect(dbViolations.some((v) => v.rule === "add_all_linux_capabilities")).toBe(true);
      expect(dbViolations.some((v) => v.rule === "disable_seccomp")).toBe(true);
      expect(dbViolations.some((v) => v.rule === "expose_database_publicly")).toBe(true);
      expect(dbViolations.some((v) => v.rule === "mount_docker_socket")).toBe(true);
      expect(dbViolations.some((v) => v.rule === "mount_host_root")).toBe(true);
      expect(dbViolations.some((v) => v.rule === "restart_policy")).toBe(true);
      expect(dbViolations.some((v) => v.rule === "non_root_user")).toBe(true);
      expect(dbViolations.some((v) => v.rule === "project_labels")).toBe(true);
      expect(dbViolations.some((v) => v.rule === "resource_limits")).toBe(true);
      expect(dbViolations.some((v) => v.rule === "logging_rotation")).toBe(true);
      expect(dbViolations.some((v) => v.rule === "healthcheck")).toBe(true);
      expect(dbViolations.some((v) => v.rule === "read_only_root_filesystem_when_possible" && v.severity === "warn")).toBe(true);

      expect(webViolations.some((v) => v.rule === "untrusted_registry")).toBe(true);
      expect(webViolations.some((v) => v.rule === "resource_limits" && v.message.includes("exceeds"))).toBe(true);
      expect(webViolations.some((v) => v.rule === "logging_rotation" && v.message.includes("max-size"))).toBe(true);
      expect(webViolations.some((v) => v.rule === "logging_rotation" && v.message.includes("max-file"))).toBe(true);
      expect(webViolations.some((v) => v.rule === "healthcheck" && v.message.includes("interval"))).toBe(true);
      expect(webViolations.some((v) => v.rule === "healthcheck" && v.message.includes("timeout"))).toBe(true);
    });
  });
});
