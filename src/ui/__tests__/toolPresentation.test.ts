import { describe, expect, it } from "vitest";
import { type ToolPresentation, presentTool, sanitizeToolText } from "../toolPresentation";

describe("presentTool", () => {
  const cases: Array<{
    name: string;
    input: unknown;
    output?: unknown;
    expectedTitle: string;
    expectedSummary: string;
    checkDetail?: (d: string[]) => void;
  }> = [
    {
      name: "plan_stack",
      input: { stackName: "web", intent: "deploy web app", services: { app: { image: "nginx" } } },
      output: {
        blocked: false,
        composeYaml: "services:\n  app:\n    image: nginx\n",
        diff: { stackName: "web", status: "missing", serviceDiffs: [] },
      },
      expectedTitle: "Plan stack: web",
      expectedSummary: "Generate Compose plan for web (deploy web app)",
      checkDetail: (d) => {
        expect(d.some((l) => l.includes("nginx"))).toBe(true);
      },
    },
    {
      name: "apply_stack",
      input: { stackName: "web", composeYaml: "services:\n  app:\n    image: nginx\n" },
      output: { ok: true, exitCode: 0, yamlPath: "/path/to/web.yaml", healthy: true },
      expectedTitle: "Apply stack: web",
      expectedSummary: "Deploy stack web",
      checkDetail: (d) => {
        expect(d.some((l) => l.includes("healthy"))).toBe(true);
      },
    },
    {
      name: "destroy_stack",
      input: { stackName: "web", removeVolumes: true },
      output: { ok: true, exitCode: 0 },
      expectedTitle: "Destroy stack: web",
      expectedSummary: "Tear down stack web (volumes removed)",
      checkDetail: (d) => {
        expect(d.some((l) => l.includes("exitCode"))).toBe(true);
      },
    },
    {
      name: "destroy_all_stacks",
      input: { removeVolumes: false },
      output: { destroyed: ["web"], failed: [] },
      expectedTitle: "Destroy all stacks",
      expectedSummary: "Tear down all stacks",
      checkDetail: (d) => {
        expect(d.some((l) => l.includes("web"))).toBe(true);
      },
    },
    {
      name: "list_stacks",
      input: {},
      output: { stacks: [{ name: "web", createdAt: "2024-01-01", services: ["app"] }] },
      expectedTitle: "List stacks",
      expectedSummary: "List all stacks",
      checkDetail: (d) => {
        expect(d.some((l) => l.includes("web"))).toBe(true);
      },
    },
    {
      name: "inspect_drift",
      input: { stackName: "web" },
      output: { stackName: "web", status: "in_sync", serviceDiffs: [] },
      expectedTitle: "Inspect drift: web",
      expectedSummary: "Compare desired vs actual for web",
    },
    {
      name: "remediate_drift",
      input: { stackName: "web" },
      output: {
        diff: { stackName: "web", status: "drift", serviceDiffs: [] },
        desiredYaml: "yaml",
        remediable: true,
      },
      expectedTitle: "Remediate drift: web",
      expectedSummary: "Detect drift and prepare remediation for web",
      checkDetail: (d) => {
        expect(d.some((l) => l.includes("remediable"))).toBe(true);
      },
    },
    {
      name: "get_stack_status",
      input: { stackName: "web", tailLines: 50 },
      output: { rows: [{ Name: "web_app_1", State: "running" }], logTail: "log line\n" },
      expectedTitle: "Stack status: web",
      expectedSummary: "Container state and logs for web",
      checkDetail: (d) => {
        expect(d.some((l) => l.includes("running"))).toBe(true);
      },
    },
    {
      name: "get_logs",
      input: { stackName: "web", service: "app", tailLines: 100 },
      output: { logTail: "log line\n", lineCount: 1, truncated: false },
      expectedTitle: "Logs: web/app",
      expectedSummary: "Fetch logs for web (service: app)",
      checkDetail: (d) => {
        expect(d.some((l) => l.includes("lineCount"))).toBe(true);
      },
    },
    {
      name: "get_health",
      input: { stackName: "web" },
      output: {
        containers: [
          {
            name: "web_app_1",
            service: "app",
            status: "running",
            cpuPercent: 5,
            memUsedMb: 100,
            memLimitMb: 512,
            memPercent: 19.5,
            restartCount: 0,
            crashLoop: false,
          },
        ],
        crashLoops: [],
      },
      expectedTitle: "Health: web",
      expectedSummary: "Per-container health and stats for web",
      checkDetail: (d) => {
        expect(d.some((l) => l.includes("running"))).toBe(true);
      },
    },
    {
      name: "pull_image",
      input: { image: "nginx:latest" },
      output: { ok: true, status: "valid", source: "pulled" },
      expectedTitle: "Pull image: nginx:latest",
      expectedSummary: "Validate and pull nginx:latest",
      checkDetail: (d) => {
        expect(d.some((l) => l.includes("pulled"))).toBe(true);
      },
    },
    {
      name: "exec_docker",
      input: { args: ["ps", "-a"] },
      output: { exitCode: 0, stdout: "CONTAINER ID...", stderr: "" },
      expectedTitle: "Docker: ps -a",
      expectedSummary: "Run docker ps -a",
      checkDetail: (d) => {
        expect(d.some((l) => l.includes("stdout"))).toBe(true);
      },
    },
  ];

  it.each(cases)(
    "registers presentation for $name",
    ({ name, input, output, expectedTitle, expectedSummary, checkDetail }) => {
      const p = presentTool(name, input, output);
      expect(p.title).toBe(expectedTitle);
      expect(p.summary).toBe(expectedSummary);
      if (checkDetail) checkDetail(p.detailLines);
    },
  );

  it("falls back for unknown tool name", () => {
    const p = presentTool("unknown_tool", { foo: "bar" }, { result: 1 });
    expect(p.title).toBe("Tool: unknown_tool");
    expect(p.summary).toBe("Run unknown_tool");
    expect(p.detailLines.length).toBeGreaterThan(0);
  });

  it("does not expose credentials in titles or summaries", () => {
    const presentation = presentTool("exec_docker", {
      args: ["login", "--password", "hunter2"],
    });
    expect(presentation.title).not.toContain("hunter2");
    expect(presentation.summary).not.toContain("hunter2");
  });

  it("truncates detail lines to 20 lines", () => {
    const longOutput = Array.from({ length: 50 }, (_, i) => `line ${i}`).join("\n");
    const p = presentTool(
      "exec_docker",
      { args: ["logs", "c"] },
      { exitCode: 0, stdout: longOutput, stderr: "" },
    );
    expect(p.detailLines.length).toBeLessThanOrEqual(20);
  });

  it("truncates detail bytes to 4096", () => {
    const longOutput = "x".repeat(10_000);
    const p = presentTool(
      "exec_docker",
      { args: ["logs", "c"] },
      { exitCode: 0, stdout: longOutput, stderr: "" },
    );
    const total = p.detailLines.join("\n").length;
    expect(total).toBeLessThanOrEqual(4096);
  });

  it("masks secret-like keys in detail", () => {
    const p = presentTool("plan_stack", {
      stackName: "web",
      services: {
        app: {
          image: "x",
          environment: {
            apiKey: "super-secret",
            password: "hunter2",
            token: "tok",
            secret: "sec",
            credential: "cred",
          },
        },
      },
    });
    const text = p.detailLines.join("\n");
    expect(text).not.toContain("super-secret");
    expect(text).not.toContain("hunter2");
    expect(text).not.toContain("tok");
    expect(text).not.toContain("sec");
    expect(text).not.toContain("cred");
    expect(text).toContain("***");
  });
});

describe("sanitizeToolText", () => {
  it("masks values for secret-like keys case-insensitively", () => {
    const text = JSON.stringify({
      APIKEY: "abc",
      MyPassword: "def",
      token: "ghi",
      SECRET_VALUE: "jkl",
      someCredential: "mno",
    });
    const sanitized = sanitizeToolText(text);
    expect(sanitized).not.toContain("abc");
    expect(sanitized).not.toContain("def");
    expect(sanitized).not.toContain("ghi");
    expect(sanitized).not.toContain("jkl");
    expect(sanitized).not.toContain("mno");
  });

  it("truncates to 4096 bytes", () => {
    const long = "a".repeat(10_000);
    const sanitized = sanitizeToolText(long);
    expect(Buffer.byteLength(sanitized, "utf-8")).toBeLessThanOrEqual(4096);
  });
});
