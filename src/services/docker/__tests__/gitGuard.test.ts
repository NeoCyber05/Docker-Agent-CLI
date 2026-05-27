import { describe, expect, test } from "vitest";
import { checkEnvFileGitStatus, type GitRunner } from "src/services/docker/gitGuard";

class StubGit implements GitRunner {
  hasGit = true;
  lsFiles: Record<string, number> = {};
  checkIgnore: Record<string, number> = {};
  async run(args: string[], _cwd: string): Promise<number> {
    if (args[0] === "ls-files") return this.lsFiles[args[args.length - 1] ?? ""] ?? 1;
    if (args[0] === "check-ignore") return this.checkIgnore[args[args.length - 1] ?? ""] ?? 1;
    return 1;
  }
  exists(): boolean {
    return this.hasGit;
  }
}

describe("gitGuard", () => {
  test("tracked file → status='tracked', refused", async () => {
    const git = new StubGit();
    git.lsFiles[".env.api"] = 0;
    const status = await checkEnvFileGitStatus([".env.api"], "/cwd", git);
    expect(status.refusals).toEqual([".env.api"]);
  });

  test("untracked + ignored → no refusal, no warning", async () => {
    const git = new StubGit();
    git.checkIgnore[".env.api"] = 0;
    const status = await checkEnvFileGitStatus([".env.api"], "/cwd", git);
    expect(status.refusals).toEqual([]);
    expect(status.warnings).toEqual([]);
  });

  test("untracked + not ignored → warning", async () => {
    const git = new StubGit();
    const status = await checkEnvFileGitStatus([".env.api"], "/cwd", git);
    expect(status.warnings).toEqual([".env.api"]);
  });

  test("no .git → skipped entirely", async () => {
    const git = new StubGit();
    git.hasGit = false;
    const status = await checkEnvFileGitStatus([".env.api"], "/cwd", git);
    expect(status).toEqual({ refusals: [], warnings: [], skipped: true });
  });
});