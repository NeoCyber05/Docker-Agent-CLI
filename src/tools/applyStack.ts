import * as fs from "node:fs";
import * as path from "node:path";
import type { Tool, ToolProgress } from "src/Tool";
import { checkEnvFileGitStatus } from "src/services/docker/gitGuard";
import { parseStackDefinition } from "src/state/StateStore";
import { readEnvFile } from "src/state/envFile";
import { scrubLine, shouldRedact } from "src/state/secretRedactor";
import type { StackDefinition } from "src/types/stack";
import { parse as parseYaml } from "yaml";
import { z } from "zod";

export const ApplyStackInputSchema = z.object({
  stackName: z.string(),
  composeYaml: z.string(),
  scaleOverrides: z.record(z.number().int().min(1)).optional(),
});

export type ApplyStackInput = z.infer<typeof ApplyStackInputSchema>;

export interface ApplyStackResult {
  ok: boolean;
  exitCode: number;
  yamlPath: string;
  errorOutput?: string;
}

function resolveEnvFile(cwd: string, envFilePath: string): string {
  return path.isAbsolute(envFilePath) ? envFilePath : path.join(cwd, envFilePath);
}

function stackEnvFiles(def: StackDefinition): string[] {
  const envFiles = new Set<string>();
  for (const spec of Object.values(def.services)) {
    for (const envFile of spec.env_file ?? []) {
      envFiles.add(envFile);
    }
  }
  return [...envFiles];
}

function stackSecretKeys(def: StackDefinition, cwd: string): Set<string> {
  const keys = new Set<string>();
  for (const source of Object.values(def["x-docker-agent"].envFileSources)) {
    for (const key of source.addedKeys ?? []) {
      keys.add(key);
    }
  }
  for (const spec of Object.values(def.services)) {
    for (const key of Object.keys(spec.environment ?? {})) {
      if (shouldRedact(key)) keys.add(key);
    }
    for (const envFile of spec.env_file ?? []) {
      const values = readEnvFile(resolveEnvFile(cwd, envFile));
      for (const key of Object.keys(values)) {
        if (shouldRedact(key)) keys.add(key);
      }
    }
  }
  return keys;
}

export const applyStack: Tool<ApplyStackInput, ApplyStackResult> = {
  name: "apply_stack",
  description: "Apply a planned stack: write YAML, run Compose up via ComposeRunner.",
  inputSchema: ApplyStackInputSchema,
  category: "high-level",
  needsPermission: () => true,
  call: async function* (input, ctx): AsyncGenerator<ToolProgress, ApplyStackResult> {
    const yamlPath = path.join(ctx.cwd, ".docker-agent", "stacks", `${input.stackName}.yaml`);
    const def = parseStackDefinition(parseYaml(input.composeYaml), "apply_stack input");
    const envFiles = stackEnvFiles(def);
    const gitStatus = await checkEnvFileGitStatus(envFiles, ctx.cwd);
    if (gitStatus.refusals.length > 0) {
      return {
        ok: false,
        exitCode: 1,
        yamlPath,
        errorOutput: gitStatus.refusals
          .map((file) => `${file} is tracked by git. Run 'git rm --cached ${file}' first.`)
          .join("\n"),
      };
    }
    for (const file of gitStatus.warnings) {
      yield {
        type: "progress",
        msg: `warning: ${file} is neither tracked nor ignored. Add '.env*' to .gitignore to prevent accidental commit.`,
      };
    }

    const secretKeys = stackSecretKeys(def, ctx.cwd);

    yield { type: "progress", msg: `Writing stack YAML for ${input.stackName}...` };

    const stacksDir = path.join(ctx.cwd, ".docker-agent", "stacks");
    fs.mkdirSync(stacksDir, { recursive: true });
    ctx.stateStore.write(input.stackName, def);

    yield { type: "progress", msg: "Acquiring stack lock..." };
    const release = await ctx.stateStore.acquireLock(input.stackName, { timeoutMs: 30_000 });

    try {
      yield { type: "progress", msg: "Running Compose up -d..." };
      const bound = ctx.composeRunner.forStack(input.stackName, yamlPath);
      const gen = bound.up({
        detach: true,
        ...(input.scaleOverrides ? { scale: input.scaleOverrides } : {}),
      });

      let captured = "";
      while (true) {
        const r = await gen.next();
        if (r.done) {
          ctx.stateStore.appendHistory({
            ts: new Date().toISOString(),
            sessionId: "unknown",
            stackName: input.stackName,
            action: "apply",
            details: { exitCode: r.value },
          });

          if (r.value !== 0) {
            return { ok: false, exitCode: r.value, yamlPath, errorOutput: captured };
          }
          ctx.stateStore.write(input.stackName, {
            ...def,
            "x-docker-agent": {
              ...def["x-docker-agent"],
              lastApplied: new Date().toISOString(),
            },
          });
          return { ok: true, exitCode: r.value, yamlPath };
        }

        const scrubbed = scrubLine(r.value, secretKeys);
        captured += scrubbed;
        yield { type: "progress", msg: scrubbed.trimEnd() };
      }
    } finally {
      release();
    }
  },
};
