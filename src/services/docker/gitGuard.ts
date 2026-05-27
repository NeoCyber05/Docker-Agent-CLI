import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";

export interface GitRunner {
  exists(cwd: string): boolean;
  run(args: string[], cwd: string): Promise<number>;
}

const realGit: GitRunner = {
  exists: (cwd) => fs.existsSync(path.join(cwd, ".git")),
  run: (args, cwd) =>
    new Promise((resolve) => {
      const c = spawn("git", args, { cwd, stdio: "ignore" });
      c.on("close", (code) => resolve(code ?? 1));
      c.on("error", () => resolve(1));
    }),
};

export interface GitStatusReport {
  refusals: string[];
  warnings: string[];
  skipped: boolean;
}

export async function checkEnvFileGitStatus(
  envFiles: string[],
  cwd: string,
  git: GitRunner = realGit,
): Promise<GitStatusReport> {
  if (!git.exists(cwd)) return { refusals: [], warnings: [], skipped: true };
  const refusals: string[] = [];
  const warnings: string[] = [];
  for (const f of envFiles) {
    const tracked = (await git.run(["ls-files", "--error-unmatch", "--", f], cwd)) === 0;
    if (tracked) {
      refusals.push(f);
      continue;
    }
    const ignored = (await git.run(["check-ignore", "-q", "--", f], cwd)) === 0;
    if (!ignored) warnings.push(f);
  }
  return { refusals, warnings, skipped: false };
}
