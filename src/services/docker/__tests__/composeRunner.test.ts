import { describe, expect, test, vi } from "vitest";
import { ComposeRunner, type Spawner } from "src/services/docker/composeRunner";

class StubSpawner implements Spawner {
  calls: Array<{ cmd: string; args: string[]; cwd: string }> = [];
  stdout = ["fake stdout line\n"];
  exit = 0;
  spawn = vi.fn(async function* (
    this: StubSpawner,
    cmd: string,
    args: string[],
    opts: { cwd: string },
  ): AsyncGenerator<string, number> {
    this.calls.push({ cmd, args, cwd: opts.cwd });
    for (const line of this.stdout) yield line;
    return this.exit;
  }.bind(this));
}

describe("ComposeRunner", () => {
  test("forStack().up emits docker compose -p NAME --project-directory CWD -f YAML up -d", async () => {
    const spawner = new StubSpawner();
    const runner = new ComposeRunner("/cwd", spawner);
    const bound = runner.forStack("webapp", "/cwd/.docker-agent/stacks/webapp.yaml");
    const out: string[] = [];
    let exit = -1;
    const gen = bound.up({ detach: true });
    while (true) {
      const r = await gen.next();
      if (r.done) {
        exit = r.value;
        break;
      }
      out.push(r.value);
    }
    expect(exit).toBe(0);
    expect(spawner.calls).toHaveLength(1);
    expect(spawner.calls[0]!).toEqual({
      cmd: "docker",
      args: [
        "compose",
        "-p",
        "webapp",
        "--project-directory",
        "/cwd",
        "-f",
        "/cwd/.docker-agent/stacks/webapp.yaml",
        "up",
        "-d",
      ],
      cwd: "/cwd",
    });
    expect(out.join("")).toContain("fake stdout line");
  });

  test("up with scale appends --scale flags", async () => {
    const spawner = new StubSpawner();
    const runner = new ComposeRunner("/cwd", spawner);
    const bound = runner.forStack("s", "/y.yaml");
    const gen = bound.up({ detach: true, scale: { api: 2, worker: 3 } });
    while (!(await gen.next()).done) {
      /* drain */
    }
    expect(spawner.calls).toHaveLength(1);
    expect(spawner.calls[0]!.args).toEqual(
      expect.arrayContaining(["--scale", "api=2", "--scale", "worker=3"]),
    );
  });

  test("down with volumes uses -v", async () => {
    const spawner = new StubSpawner();
    const runner = new ComposeRunner("/cwd", spawner);
    const bound = runner.forStack("s", "/y.yaml");
    const gen = bound.down({ volumes: true });
    while (!(await gen.next()).done) {
      /* drain */
    }
    expect(spawner.calls).toHaveLength(1);
    expect(spawner.calls[0]!.args).toContain("-v");
    expect(spawner.calls[0]!.args).toContain("down");
  });

  test("ps json returns parsed JSON lines", async () => {
    const spawner = new StubSpawner();
    spawner.stdout = [
      JSON.stringify({ Name: "s-web-1", Service: "web", State: "running" }) + "\n",
      JSON.stringify({ Name: "s-db-1", Service: "db", State: "running" }) + "\n",
    ];
    const runner = new ComposeRunner("/cwd", spawner);
    const rows = await runner.forStack("s", "/y.yaml").ps({ json: true });
    expect(rows).toEqual([
      { Name: "s-web-1", Service: "web", State: "running" },
      { Name: "s-db-1", Service: "db", State: "running" },
    ]);
  });

  test("ps returns empty array when no rows", async () => {
    const spawner = new StubSpawner();
    spawner.stdout = [];
    const runner = new ComposeRunner("/cwd", spawner);
    const rows = await runner.forStack("s", "/y.yaml").ps({ json: true });
    expect(rows).toEqual([]);
  });

  test("ps without json flag still collects output", async () => {
    const spawner = new StubSpawner();
    spawner.stdout = ["NAME           SERVICE   STATE\n", "s-web-1       web       running\n"];
    const runner = new ComposeRunner("/cwd", spawner);
    const rows = await runner.forStack("s", "/y.yaml").ps({});
    expect(rows).toEqual([]);
    expect(spawner.calls).toHaveLength(1);
    expect(spawner.calls[0]!.args).toContain("ps");
    expect(spawner.calls[0]!.args).not.toContain("--format");
  });

  test("logs yields output with service and tail filters", async () => {
    const spawner = new StubSpawner();
    const runner = new ComposeRunner("/cwd", spawner);
    const bound = runner.forStack("svc", "/y.yaml");
    const out: string[] = [];
    for await (const chunk of bound.logs({ service: "api", tailLines: 50 })) {
      out.push(chunk);
    }
    expect(spawner.calls).toHaveLength(1);
    expect(spawner.calls[0]!.args).toContain("logs");
    expect(spawner.calls[0]!.args).toContain("--tail");
    expect(spawner.calls[0]!.args).toContain("50");
    expect(spawner.calls[0]!.args).toContain("api");
  });

  test("non-zero exit code propagates from up", async () => {
    const spawner = new StubSpawner();
    spawner.exit = 1;
    spawner.stdout = ["error output\n"];
    const runner = new ComposeRunner("/cwd", spawner);
    const bound = runner.forStack("s", "/y.yaml");
    let exit = -1;
    for await (const _ of bound.up({ detach: true })) {
      /* drain */
    }
    const gen2 = bound.up({ detach: true });
    while (true) {
      const r = await gen2.next();
      if (r.done) {
        exit = r.value;
        break;
      }
    }
    expect(exit).toBe(1);
  });
});