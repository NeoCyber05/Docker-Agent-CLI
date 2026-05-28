import { Command } from "commander";
import { render } from "ink";
import React from "react";
import { resolveProvider, projectStateDir } from "./config";
import { QueryEngine } from "./QueryEngine";
import { REPL } from "./screens/REPL";
import { resolveProviderForRequest } from "./services/api";
import { ComposeRunner } from "./services/docker/composeRunner";
import Docker from "dockerode";
import type { EngineClient } from "./services/docker/engineClient";
import { StateStore } from "./state/StateStore";

const VERSION = "0.1.0";

function buildDockerEngine(): EngineClient {
  const docker = new Docker();
  return {
    async listContainers(opts) {
      const list = await docker.listContainers({
        all: opts.all ?? false,
        ...(opts.filters
          ? { filters: opts.filters as unknown as { [key: string]: string[] } }
          : {}),
      });
      return list.map((c) => ({
        Id: c.Id,
        Names: c.Names,
        State: c.State,
        Labels: c.Labels ?? {},
      }));
    },
    async inspect(id) {
      const info = await docker.getContainer(id).inspect();
      return info as unknown as ReturnType<EngineClient["inspect"]> extends Promise<infer R> ? R : never;
    },
  };
}

async function startRepl(opts: { provider?: string }): Promise<number> {
  const providerName = resolveProvider(opts.provider ? { flag: opts.provider } : {});
  const provider = resolveProviderForRequest(providerName);
  const cwd = process.cwd();
  const stateStore = new StateStore(projectStateDir());
  const composeRunner = new ComposeRunner(cwd);
  const dockerEngine = buildDockerEngine();

  const { waitUntilExit } = render(
    React.createElement(REPL, {
      version: VERSION,
      deps: {
        cwd,
        stateStore,
        dockerEngine,
        composeRunner,
        provider,
        providerName,
      },
    }),
  );
  await waitUntilExit();
  return 0;
}

export async function main(argv: string[]): Promise<number> {
  const program = new Command();
  program
    .name("docker-agent")
    .description("Natural-language CLI for managing Docker infrastructure")
    .version(VERSION, "-v, --version", "print version")
    .option("--provider <name>", "LLM provider (gemini|openai|ollama)")
    .action(async (opts: { provider?: string }) => {
      await startRepl(opts);
    });

  program.exitOverride();
  try {
    await program.parseAsync(argv);
    return 0;
  } catch (err) {
    if ((err as { code?: string }).code === "commander.version") return 0;
    if ((err as { code?: string }).code === "commander.helpDisplayed") return 0;
    process.stderr.write(`${(err as Error).message}\n`);
    return 1;
  }
}
