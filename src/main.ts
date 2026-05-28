import { Command } from "commander";

export interface ParsedArgs {
  command: "chat" | "status" | "destroy" | "plan" | "version" | "help";
  stack?: string;
  intent?: string;
  volumes?: boolean;
  yes?: boolean;
  all?: boolean;
  confirm?: string;
  providerFlag?: string;
  model?: string;
}

export function parseArgs(argv: string[]): ParsedArgs {
  const program = new Command();
  let parsed: ParsedArgs = { command: "chat" };
  program
    .name("docker-agent")
    .description("Natural-language CLI for managing Docker infrastructure")
    .version("0.1.0", "-v, --version")
    .option("--provider <name>", "LLM provider: gemini, openai, ollama")
    .option("--model <id>", "model id");

  program
    .command("chat", { isDefault: true })
    .option("-y, --yes", "auto-approve non-destructive permissions")
    .action((opts) => {
      parsed = { ...parsed, command: "chat", ...opts };
    });
  program.command("status [stack]").action((stack: string | undefined) => {
    parsed = { ...parsed, command: "status", ...(stack ? { stack } : {}) };
  });
  program
    .command("destroy [stack]")
    .option("--volumes")
    .option("--all")
    .option("-y, --yes")
    .option("--confirm <phrase>")
    .action((stack: string | undefined, opts: Record<string, unknown>) => {
      parsed = {
        ...parsed,
        command: "destroy",
        ...(stack ? { stack } : {}),
        ...(opts.volumes ? { volumes: true } : {}),
        ...(opts.yes ? { yes: true } : {}),
        ...(opts.all ? { all: true } : {}),
        ...(typeof opts.confirm === "string" ? { confirm: opts.confirm } : {}),
      };
    });
  program.command("plan <intent...>").action((intent: string[]) => {
    parsed = { ...parsed, command: "plan", intent: intent.join(" ") };
  });

  program.hook("preAction", (_thisCmd, actionCmd) => {
    const opts = actionCmd.optsWithGlobals();
    if (opts.provider) parsed.providerFlag = String(opts.provider);
    if (opts.model) parsed.model = String(opts.model);
  });

  program.exitOverride();
  try {
    program.parse(argv);
  } catch (err) {
    const code = (err as { code?: string }).code;
    if (code === "commander.version") parsed.command = "version";
    else if (code === "commander.helpDisplayed") parsed.command = "help";
    else throw err;
  }
  return parsed;
}

async function createDeps(args: ParsedArgs) {
  const { StateStore } = await import("./state/StateStore");
  const { ComposeRunner } = await import("./services/docker/composeRunner");
  const { createEngineClient } = await import("./services/docker/engineClient");
  const { resolveProviderForRequest } = await import("./services/api");
  const { resolveProvider, projectStateDir } = await import("./config");
  const providerName = resolveProvider({
    ...(args.providerFlag ? { flag: args.providerFlag } : {}),
  });
  const cwd = process.cwd();
  const stateStore = new StateStore(projectStateDir());
  const composeRunner = new ComposeRunner(cwd);
  const dockerEngine = createEngineClient();
  const provider = resolveProviderForRequest(providerName);
  return { cwd, stateStore, composeRunner, dockerEngine, provider };
}

export async function main(argv: string[]): Promise<number> {
  let args: ParsedArgs;
  try {
    args = parseArgs(argv);
  } catch (err) {
    process.stderr.write(`${(err as Error).message}\n`);
    return 1;
  }
  if (args.command === "version" || args.command === "help") return 0;

  if (args.command === "chat") {
    const { render } = await import("ink");
    const React = await import("react");
    const { REPL } = await import("./screens/REPL");
    const { resolveProvider } = await import("./config");
    const providerName = resolveProvider({
      ...(args.providerFlag ? { flag: args.providerFlag } : {}),
    });
    const deps = await createDeps(args);
    const { waitUntilExit } = render(
      React.createElement(REPL, {
        deps: { ...deps, providerName, ...(args.yes ? { yes: true } : {}) },
      }),
    );
    await waitUntilExit();
    return 0;
  }

  if (args.command === "status") {
    return await runHeadless(`show status of ${args.stack ?? "all stacks"}`, args);
  }

  if (args.command === "destroy") {
    if (args.all) {
      if (args.confirm !== "DESTROY ALL") {
        process.stderr.write('destroy --all requires --confirm "DESTROY ALL"\n');
        return 1;
      }
      return await runHeadless("destroy all stacks", args);
    }
    if (!args.stack) {
      process.stderr.write("destroy requires a stack name or --all\n");
      return 1;
    }
    return await runHeadless(`destroy ${args.stack}${args.volumes ? " with volumes" : ""}`, args);
  }

  if (args.command === "plan") {
    return await runHeadless(args.intent ?? "", args);
  }
  return 0;
}

export async function runHeadless(prompt: string, args: ParsedArgs): Promise<number> {
  const { QueryEngine } = await import("./QueryEngine");
  const deps = await createDeps(args);
  const engine = new QueryEngine(deps);
  let hasError = false;
  for await (const ev of engine.query(prompt)) {
    if (ev.type === "assistant_text") process.stdout.write(ev.delta);
    if (ev.type === "plan_ready") {
      if (args.yes) engine.respondTo(ev.id, { kind: "approve" });
      else engine.respondTo(ev.id, { kind: "deny" });
    }
    if (ev.type === "permission_request") {
      if (args.yes) engine.respondTo(ev.id, { kind: "approve" });
      else engine.respondTo(ev.id, { kind: "deny" });
    }
    if (ev.type === "typed_confirm_request") {
      if (args.confirm === ev.phrase) {
        engine.respondTo(ev.id, { kind: "typed_confirm_value", value: ev.phrase });
      } else {
        engine.respondTo(ev.id, { kind: "deny" });
      }
    }
    if (ev.type === "secrets_input_request") {
      process.stderr.write(
        `headless: required secrets for ${ev.service} not provided. Use chat mode.\n`,
      );
      engine.respondTo(ev.id, { kind: "deny" });
    }
    if (ev.type === "error") {
      process.stderr.write(`error: ${ev.error.message}\n`);
      hasError = true;
    }
  }
  return hasError ? 1 : 0;
}
