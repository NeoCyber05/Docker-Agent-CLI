import * as fs from "node:fs";
import * as path from "node:path";
import { spawn } from "node:child_process";

export interface GitRunner {
  exists(): boolean;
  run(args: string[], cwd: string): Promise<number>;
}

const realGit: GitRunner = {
  exists: () => fs.existsSync(path.join(process.cwd(), ".git")),
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
  if (!git.exists()) return { refusals: [], warnings: [], skipped: true };
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