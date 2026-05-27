import { spawn } from "node:child_process";
import type { Tool, ToolProgress } from "src/Tool";
import { z } from "zod";

const SIMPLE_READ_ONLY = new Set(["ps", "inspect", "logs", "images"]);
const READ_ONLY_GROUPS = new Set(["network", "volume"]);
const REJECTED = new Set(["rm", "kill", "prune", "exec", "stop", "restart", "system"]);

function isAllowedDockerArgs(args: string[]): boolean {
  const head = args[0];
  if (head === undefined || REJECTED.has(head)) return false;
  if (SIMPLE_READ_ONLY.has(head)) return true;
  return READ_ONLY_GROUPS.has(head) && args[1] === "ls";
}

export const ExecDockerInputSchema = z
  .object({ args: z.array(z.string()).min(1) })
  .refine((value) => isAllowedDockerArgs(value.args), {
    message: "subcommand not in read-only whitelist",
  });

export type ExecDockerInput = z.infer<typeof ExecDockerInputSchema>;

export interface ExecDockerResult {
  exitCode: number;
  stdout: string;
  stderr: string;
}

export const execDocker: Tool<ExecDockerInput, ExecDockerResult> = {
  name: "exec_docker",
  description:
    "Run a read-only docker subcommand (ps, inspect, logs, images, network ls, volume ls).",
  inputSchema: ExecDockerInputSchema,
  category: "escape-hatch",
  needsPermission: () => true,
  call: async function* (input, ctx): AsyncGenerator<ToolProgress, ExecDockerResult> {
    yield { type: "progress", msg: `docker ${input.args.join(" ")}` };

    const child = spawn("docker", input.args, {
      cwd: ctx.cwd,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";

    child.stdout?.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr?.on("data", (chunk) => {
      stderr += String(chunk);
    });

    const exitCode = await new Promise<number>((resolve) => {
      child.on("error", (error) => {
        stderr += String(error);
        resolve(1);
      });
      child.on("close", (code) => resolve(code ?? 0));
    });

    return { exitCode, stdout, stderr };
  },
};
