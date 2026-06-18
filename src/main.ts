import { Readable, Writable } from "node:stream";
import { Command } from "commander";
import { render } from "ink";
import React from "react";
import { QueryEngine, type QueryEngineDeps } from "./QueryEngine";
import { WelcomeBanner } from "./components/WelcomeBanner";
import { loadUserConfig, projectStateDir, resolveProvider } from "./config";
import { REPL } from "./screens/REPL";
import { type ApiKeyStore, createApiKeyStore } from "./secrets/apiKeyStore";
import { resolveProviderForRequest } from "./services/api";
import { ComposeRunner } from "./services/docker/composeRunner";
import { createEngineClient } from "./services/docker/engineClient";
import { SessionStore } from "./state/SessionStore";
import { StateStore } from "./state/StateStore";

const VERSION = "0.1.0";
const COMPACT_WELCOME_MAX_ROWS = 16;
const COMPACT_WELCOME_MAX_COLUMNS = 84;

type ChatRender = (
  node: React.ReactElement,
  options?: { exitOnCtrlC?: boolean },
) => {
  waitUntilExit(): Promise<void>;
};

class BufferedStdout extends Writable {
  isTTY = true;
  columns: number;
  rows: number;
  private chunks: string[] = [];

  constructor({ columns, rows }: { columns: number; rows: number }) {
    super();
    this.columns = columns;
    this.rows = rows;
  }

  _write(chunk: Buffer | string, _encoding: BufferEncoding, callback: (error?: Error) => void) {
    this.chunks.push(String(chunk));
    callback();
  }

  output(): string {
    return this.chunks.join("");
  }
}

class BufferedStdin extends Readable {
  isTTY = false;
  setRawMode() {
    return this;
  }

  _read() {}
}

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
  resume?: string | true; // true = latest, string = specific id
}

export function parseArgs(argv: string[]): ParsedArgs {
  const program = new Command();
  let parsed: ParsedArgs = { command: "chat" };
  program
    .name("docker-agent")
    .description("Natural-language CLI for managing Docker infrastructure")
    .version(VERSION, "-v, --version")
    .option("--provider <name>", "LLM provider: gemini, openai, ollama")
    .option("--model <id>", "model id");

  program
    .command("chat", { isDefault: true })
    .option("-y, --yes", "auto-approve non-destructive permissions")
    .option("--resume [id]", "resume a previous session (omit id for latest)")
    .action((opts) => {
      parsed = {
        ...parsed,
        command: "chat",
        ...opts,
        // normalize: --resume with no value comes in as true, with value as string
        ...(opts.resume !== undefined
          ? { resume: opts.resume === true || opts.resume === "" ? true : opts.resume }
          : {}),
      };
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
  const userConfig = loadUserConfig();
  const providerName = resolveProvider({
    ...(args.providerFlag ? { flag: args.providerFlag } : {}),
    config: userConfig,
  });
  const model = args.model ?? userConfig.model;
  const cwd = process.cwd();
  const stateStore = new StateStore(projectStateDir());
  const composeRunner = new ComposeRunner(cwd);
  const dockerEngine = createEngineClient();
  const apiKeyStore = createApiKeyStore();
  const provider = resolveProviderForRequest(providerName, process.env, { apiKeyStore });
  const sessionStore = new SessionStore(projectStateDir());
  return {
    cwd,
    stateStore,
    sessionStore,
    composeRunner,
    dockerEngine,
    provider,
    providerName,
    apiKeyStore,
    ...(model ? { model } : {}),
  };
}

export function renderWelcomeBannerForTerminal({
  provider,
  version = VERSION,
  stdout = process.stdout,
}: {
  provider: string;
  version?: string;
  stdout?: NodeJS.WriteStream;
}): string {
  const columns = stdout.columns || 80;
  const rows = stdout.rows || 24;
  const renderColumns = Math.max(1, columns - 1);
  const compact = rows <= COMPACT_WELCOME_MAX_ROWS || renderColumns < COMPACT_WELCOME_MAX_COLUMNS;
  const captureStdout = new BufferedStdout({ columns: renderColumns, rows });
  const captureStderr = new BufferedStdout({ columns: renderColumns, rows });
  const captureStdin = new BufferedStdin();
  const app = render(React.createElement(WelcomeBanner, { version, provider, compact }), {
    stdout: captureStdout as unknown as NodeJS.WriteStream,
    stderr: captureStderr as unknown as NodeJS.WriteStream,
    stdin: captureStdin as unknown as NodeJS.ReadStream,
    debug: true,
    patchConsole: false,
    exitOnCtrlC: false,
  });
  const output = captureStdout.output();
  app.unmount();
  app.cleanup();
  return output.endsWith("\n") ? output : `${output}\n`;
}

async function resolveResume(
  args: ParsedArgs,
  sessionStore: SessionStore,
): Promise<import("./state/SessionStore").SessionRecord | null> {
  if (!args.resume) return null;
  const rec =
    typeof args.resume === "string" ? sessionStore.read(args.resume) : sessionStore.latest();
  if (!rec) {
    process.stderr.write(
      args.resume === true
        ? "No previous session found to resume.\n"
        : `Session ${args.resume} not found.\n`,
    );
  }
  return rec;
}

export async function renderChatSession(
  deps: QueryEngineDeps & {
    providerName: string;
    yes?: boolean;
    apiKeyStore?: ApiKeyStore;
    resumedRecord?: import("./state/SessionStore").SessionRecord;
  },
  options: { renderImpl?: ChatRender; version?: string; showBanner?: boolean } = {},
): Promise<void> {
  const showBanner = options.showBanner ?? true;
  if (showBanner) {
    process.stdout.write(
      renderWelcomeBannerForTerminal({
        provider: deps.providerName,
        version: options.version ?? VERSION,
      }),
    );
  }
  const renderImpl = options.renderImpl ?? render;
  const { waitUntilExit } = renderImpl(
    React.createElement(REPL, {
      version: options.version ?? VERSION,
      deps,
      showBanner: false,
      ...(deps.resumedRecord ? { resumedRecord: deps.resumedRecord } : {}),
    }),
    { exitOnCtrlC: false },
  );
  await waitUntilExit();
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
    const deps = await createDeps(args);
    const resumedRecord = await resolveResume(args, deps.sessionStore);
    await renderChatSession({
      ...deps,
      ...(args.yes ? { yes: true } : {}),
      ...(resumedRecord ? { resumedRecord } : {}),
    });
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
