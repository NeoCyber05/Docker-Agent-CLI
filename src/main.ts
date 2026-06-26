import * as path from "node:path";
import { Readable, Writable } from "node:stream";
import { Command } from "commander";
import { render } from "ink";
import React from "react";
import { QueryEngine, type QueryEngineDeps } from "./QueryEngine";
import { WelcomeBanner } from "./components/WelcomeBanner";
import { loadUserConfig, projectStateDir, resolveProvider, stackStatesDir } from "./config";
import { REPL } from "./screens/REPL";
import { type ApiKeyStore, createApiKeyStore } from "./secrets/apiKeyStore";
import { resolveProviderForRequest } from "./services/api";
import { ComposeRunner } from "./services/docker/composeRunner";
import { createEngineClient } from "./services/docker/engineClient";
import { SessionStore } from "./state/SessionStore";
import { StateStore } from "./state/StateStore";
import { StructuredLogger } from "./state/logger";

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
  providerFlag?: string;
  model?: string;
  resume?: string | true; // true = latest, string = specific id
  yes?: boolean;
  isVersionOrHelp?: boolean;
}

export function parseArgs(argv: string[]): ParsedArgs {
  const program = new Command();
  program
    .name("docker-agent")
    .description("Natural-language CLI for managing Docker infrastructure")
    .version(VERSION, "-v, --version")
    .option("--provider <name>", "LLM provider: gemini, openai, ollama")
    .option("--model <id>", "model id")
    .option("-y, --yes", "auto-approve non-destructive permissions")
    .option("--resume [id]", "resume a previous session (omit id for latest)");

  program.exitOverride();
  try {
    program.parse(argv);
  } catch (err) {
    const code = (err as { code?: string }).code;
    if (code === "commander.version" || code === "commander.helpDisplayed") {
      return { isVersionOrHelp: true };
    }
    throw err;
  }

  const opts = program.opts();
  const parsed: ParsedArgs = {};
  if (opts.provider) parsed.providerFlag = String(opts.provider);
  if (opts.model) parsed.model = String(opts.model);
  if (opts.yes) parsed.yes = true;
  if (opts.resume !== undefined) {
    parsed.resume = opts.resume === true || opts.resume === "" ? true : String(opts.resume);
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
  const stateStore = new StateStore(projectStateDir(), { statesDir: stackStatesDir(cwd) });
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
    return null;
  }
  process.stderr.write(`[docker-agent] Resuming session ${rec.id}\n`);
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
  if (args.isVersionOrHelp) return 0;

  const deps = await createDeps(args);
  const resumedRecord = await resolveResume(args, deps.sessionStore);
  await renderChatSession({
    ...deps,
    ...(args.yes ? { yes: true } : {}),
    ...(resumedRecord ? { resumedRecord } : {}),
  });
  return 0;
}
