import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { ComposeRunner, type Spawner, defaultSpawner } from "src/services/docker/composeRunner";
import { describe, expect, test, vi } from "vitest";

class StubSpawner implements Spawner {
  // `signal: AbortSignal | undefined` (not `signal?:`) so pushing `opts.signal`
  // when it is undefined is legal under `exactOptionalPropertyTypes`.
  calls: Array<{ cmd: string; args: string[]; cwd: string; signal: AbortSignal | undefined }> = [];
  stdout = ["fake stdout line\n"];
  exit = 0;
  /** When true, spawn yields stdout then waits for abort before ending. */
  waitForAbort = false;
  killed = false;
  spawn = vi.fn(
    async function* (
      this: StubSpawner,
      cmd: string,
      args: string[],
      opts: { cwd: string; signal?: AbortSignal },
    ): AsyncGenerator<string, number> {
      this.calls.push({ cmd, args, cwd: opts.cwd, signal: opts.signal });
      for (const line of this.stdout) yield line;
      if (this.waitForAbort) {
        await new Promise<void>((resolve) => {
          if (opts.signal?.aborted) {
            this.killed = true;
            resolve();
            return;
          }
          opts.signal?.addEventListener(
            "abort",
            () => {
              this.killed = true;
              resolve();
            },
            { once: true },
          );
        });
      }
      return this.exit;
    }.bind(this),
  );
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
    expect(spawner.calls[0]).toEqual({
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
    expect(spawner.calls[0]?.args).toEqual(
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
    expect(spawner.calls[0]?.args).toContain("-v");
    expect(spawner.calls[0]?.args).toContain("down");
  });

  test("ps json returns parsed JSON lines", async () => {
    const spawner = new StubSpawner();
    spawner.stdout = [
      `${JSON.stringify({ Name: "s-web-1", Service: "web", State: "running" })}\n`,
      `${JSON.stringify({ Name: "s-db-1", Service: "db", State: "running" })}\n`,
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
    expect(spawner.calls[0]?.args).toContain("ps");
    expect(spawner.calls[0]?.args).not.toContain("--format");
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
    expect(spawner.calls[0]?.args).toContain("logs");
    expect(spawner.calls[0]?.args).toContain("--tail");
    expect(spawner.calls[0]?.args).toContain("50");
    expect(spawner.calls[0]?.args).toContain("api");
  });

  test("logs follow adds -f and since adds --since", async () => {
    const spawner = new StubSpawner();
    const runner = new ComposeRunner("/cwd", spawner);
    const bound = runner.forStack("svc", "/y.yaml");
    for await (const _ of bound.logs({ follow: true, since: "10m", tailLines: 50 })) {
      /* drain */
    }
    const args = spawner.calls[0]?.args ?? [];
    expect(args).toContain("-f");
    expect(args).toContain("--since");
    expect(args).toContain("10m");
    expect(args).toContain("--tail");
    expect(args).toContain("50");
  });

  test("logs threads the abort signal to the spawner", async () => {
    const spawner = new StubSpawner();
    const controller = new AbortController();
    const runner = new ComposeRunner("/cwd", spawner);
    const bound = runner.forStack("svc", "/y.yaml");
    for await (const _ of bound.logs({ signal: controller.signal })) {
      /* drain */
    }
    expect(spawner.calls[0]?.signal).toBe(controller.signal);
  });

  test("aborting the signal ends the logs generator cleanly", async () => {
    const spawner = new StubSpawner();
    spawner.waitForAbort = true;
    const controller = new AbortController();
    const runner = new ComposeRunner("/cwd", spawner);
    const bound = runner.forStack("svc", "/y.yaml");

    const collected: string[] = [];
    const iterate = (async () => {
      for await (const line of bound.logs({ follow: true, signal: controller.signal })) {
        collected.push(line);
      }
    })();

    // Let the generator emit its buffered line, then abort.
    await new Promise<void>((r) => setTimeout(r, 10));
    controller.abort();
    await iterate; // resolves only if the generator ended

    expect(collected.join("")).toContain("fake stdout line");
    expect(spawner.killed).toBe(true);
  });

  test("defaultSpawner does not hang when the signal is already aborted", async () => {
    // Regression: the close listener must be registered before the pre-aborted
    // signal is handled, otherwise `return await exitPromise` would hang forever.
    const controller = new AbortController();
    controller.abort(); // aborted BEFORE spawn is called

    // A short-lived real process; `process.execPath` keeps this cross-platform.
    const gen = defaultSpawner.spawn(process.execPath, ["-e", "setTimeout(() => {}, 60000)"], {
      cwd: process.cwd(),
      signal: controller.signal,
    });

    const done = (async () => {
      for await (const _ of gen) {
        /* drain */
      }
    })();

    // If the close listener were missing, this would never resolve.
    await expect(
      Promise.race([
        done.then(() => "done"),
        new Promise((r) => setTimeout(() => r("timeout"), 5000)),
      ]),
    ).resolves.toBe("done");
  });

  test("defaultSpawner kills the child when the consumer breaks early without aborting", async () => {
    // A child that writes a marker file after a delay. If the generator kills the
    // child on early `.return()` (consumer break), the marker is never written.
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "spawn-break-"));
    const marker = path.join(tmpDir, "marker.txt");
    const script = `setTimeout(() => require("fs").writeFileSync(${JSON.stringify(marker)}, "x"), 1000); console.log("ready");`;

    const gen = defaultSpawner.spawn(process.execPath, ["-e", script], { cwd: process.cwd() });

    // Consume the first line, then break WITHOUT aborting any signal.
    for await (const _ of gen) {
      break;
    }

    // Wait past the child's 1s marker timer; if it survived, the marker appears.
    await new Promise<void>((r) => setTimeout(r, 1500));
    expect(fs.existsSync(marker)).toBe(false);

    fs.rmSync(tmpDir, { recursive: true, force: true });
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
