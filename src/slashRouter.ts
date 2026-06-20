import type { ProviderName } from "src/config";
import type { ApiKeyStore } from "src/secrets/apiKeyStore";
import { parseProviderModel } from "src/services/modelCatalog";
import {
  destroyStackPrompt,
  dispatchSecretsList,
  dispatchStacks,
  dispatchYaml,
} from "src/slashDispatch";
import type { SessionStore } from "src/state/SessionStore";
import type { StateStore } from "src/state/StateStore";

export interface SlashCommandDef {
  usage: string;
  description: string;
  insertText: string;
}

export type SlashEffect =
  | { type: "emit_user_text"; text: string }
  | { type: "emit_assistant_text"; delta: string }
  | { type: "emit_error"; message: string }
  | { type: "submit_prompt"; prompt: string }
  | { type: "exit" }
  | { type: "clear_session" }
  | { type: "cancel_current" }
  | { type: "toggle_details" }
  | { type: "queue_resume" }
  | { type: "queue_clear" }
  | { type: "queue_remove"; index: number }
  | { type: "open_provider_connect" }
  | { type: "open_model_picker"; scopeProvider?: ProviderName }
  | { type: "set_model"; provider: ProviderName; model: string }
  | { type: "load_session"; sessionId?: string }
  | { type: "start_log_pane"; stackName: string; service?: string };

export interface SlashRouteResult {
  handled: boolean;
  effects: SlashEffect[];
}

export interface SlashRouterContext {
  cwd: string;
  stateStore: StateStore;
  sessionStore?: SessionStore;
  activeProviderName: ProviderName;
  apiKeyStore: ApiKeyStore;
  hasLatestTool: boolean;
}

export const SLASH_COMMAND_DEFS: readonly SlashCommandDef[] = [
  { usage: "/help", description: "Show slash command help", insertText: "/help" },
  { usage: "/clear", description: "Clear chat history and session state", insertText: "/clear" },
  { usage: "/exit", description: "Exit docker-agent", insertText: "/exit" },
  { usage: "/stacks", description: "List managed stacks", insertText: "/stacks" },
  {
    usage: "/status <stack>",
    description: "Show status and drift for a stack",
    insertText: "/status ",
  },
  {
    usage: "/logs <stack> [service]",
    description: "Live-tail a stack's logs (Esc to stop)",
    insertText: "/logs ",
  },
  { usage: "/destroy <stack>", description: "Destroy one stack", insertText: "/destroy " },
  {
    usage: "/destroy all",
    description: "Destroy every stack after confirmation",
    insertText: "/destroy all",
  },
  {
    usage: "/secrets list <stack>",
    description: "List secret keys for a stack",
    insertText: "/secrets list ",
  },
  {
    usage: "/secrets rotate <stack> <service>",
    description: "Rotate service secrets",
    insertText: "/secrets rotate ",
  },
  {
    usage: "/connect",
    description: "Connect a provider (API key or Ollama)",
    insertText: "/connect",
  },
  { usage: "/models", description: "Browse and select a model", insertText: "/models" },
  {
    usage: "/model <id>",
    description: "Set model override (or provider/model)",
    insertText: "/model ",
  },
  { usage: "/yaml <stack>", description: "Show stack YAML", insertText: "/yaml " },
  { usage: "/resume", description: "Resume the most recent session", insertText: "/resume" },
  { usage: "/resume <id>", description: "Resume a specific session by id", insertText: "/resume " },
  { usage: "/cancel", description: "Cancel the current turn", insertText: "/cancel" },
  { usage: "/details", description: "Open details for the latest tool", insertText: "/details" },
  {
    usage: "/queue resume",
    description: "Resume processing the queue",
    insertText: "/queue resume",
  },
  { usage: "/queue clear", description: "Clear the queued turns", insertText: "/queue clear" },
  {
    usage: "/queue remove <index>",
    description: "Remove a queued turn by index",
    insertText: "/queue remove ",
  },
];

const HANDLER_KEYS = [
  "/queue remove",
  "/queue resume",
  "/queue clear",
  "/secrets list",
  "/secrets rotate",
  "/destroy all",
  "/help",
  "/clear",
  "/exit",
  "/stacks",
  "/status",
  "/logs",
  "/destroy",
  "/secrets",
  "/connect",
  "/models",
  "/model",
  "/yaml",
  "/resume",
  "/cancel",
  "/details",
] as const;

type HandlerKey = (typeof HANDLER_KEYS)[number];

export function formatSlashHelp(): string {
  return [
    "Supported slash commands:",
    ...SLASH_COMMAND_DEFS.map((command) => `- ${command.usage}: ${command.description}`),
  ].join("\n");
}

function handleHelp(input: string): SlashRouteResult {
  return {
    handled: true,
    effects: [
      { type: "emit_user_text", text: input },
      { type: "emit_assistant_text", delta: formatSlashHelp() },
    ],
  };
}

function handleStacks(input: string, ctx: SlashRouterContext): SlashRouteResult {
  return {
    handled: true,
    effects: [
      { type: "emit_user_text", text: input },
      { type: "emit_assistant_text", delta: dispatchStacks(ctx) },
    ],
  };
}

function handleYaml(input: string, parts: string[], ctx: SlashRouterContext): SlashRouteResult {
  const stackName = parts.slice(1).join(" ").trim();
  if (!stackName) {
    return {
      handled: true,
      effects: [
        { type: "emit_user_text", text: input },
        { type: "emit_error", message: "Usage: /yaml <stack>" },
      ],
    };
  }
  const result = dispatchYaml(stackName, ctx);
  if (!result.ok) {
    return {
      handled: true,
      effects: [
        { type: "emit_user_text", text: input },
        { type: "emit_error", message: result.error },
      ],
    };
  }
  return {
    handled: true,
    effects: [
      { type: "emit_user_text", text: input },
      { type: "emit_assistant_text", delta: result.text },
    ],
  };
}

function handleSecretsList(
  input: string,
  parts: string[],
  ctx: SlashRouterContext,
): SlashRouteResult {
  const stackName = parts.slice(2).join(" ").trim();
  if (!stackName) {
    return {
      handled: true,
      effects: [
        { type: "emit_user_text", text: input },
        { type: "emit_error", message: "Usage: /secrets list <stack>" },
      ],
    };
  }
  const result = dispatchSecretsList(stackName, ctx);
  if (!result.ok) {
    return {
      handled: true,
      effects: [
        { type: "emit_user_text", text: input },
        { type: "emit_error", message: result.error },
      ],
    };
  }
  return {
    handled: true,
    effects: [
      { type: "emit_user_text", text: input },
      { type: "emit_assistant_text", delta: result.text },
    ],
  };
}

function handleSecrets(input: string): SlashRouteResult {
  return {
    handled: true,
    effects: [
      { type: "emit_user_text", text: input },
      {
        type: "emit_error",
        message: "Usage: /secrets list <stack> | /secrets rotate <stack> <service>",
      },
    ],
  };
}

function handleStatus(input: string, parts: string[]): SlashRouteResult {
  const stackName = parts.slice(1).join(" ").trim();
  if (!stackName) {
    return {
      handled: true,
      effects: [
        { type: "emit_user_text", text: input },
        { type: "emit_error", message: "Usage: /status <stack>" },
      ],
    };
  }
  return {
    handled: true,
    effects: [
      { type: "emit_user_text", text: input },
      { type: "submit_prompt", prompt: `Show status and drift for stack ${stackName}` },
    ],
  };
}

function handleDestroy(input: string, parts: string[]): SlashRouteResult {
  const arg = parts.slice(1).join(" ").trim();
  if (!arg) {
    return {
      handled: true,
      effects: [
        { type: "emit_user_text", text: input },
        { type: "emit_error", message: "Usage: /destroy <stack>" },
      ],
    };
  }
  return {
    handled: true,
    effects: [
      { type: "emit_user_text", text: input },
      { type: "submit_prompt", prompt: destroyStackPrompt(arg) },
    ],
  };
}

function handleDestroyAll(input: string): SlashRouteResult {
  return {
    handled: true,
    effects: [
      { type: "emit_user_text", text: input },
      { type: "submit_prompt", prompt: "Destroy all stacks" },
    ],
  };
}

function handleSecretsRotate(input: string, parts: string[]): SlashRouteResult {
  const subparts = parts.slice(2);
  if (subparts.length < 2 || !subparts[0] || !subparts[1]) {
    return {
      handled: true,
      effects: [
        { type: "emit_user_text", text: input },
        { type: "emit_error", message: "Usage: /secrets rotate <stack> <service>" },
      ],
    };
  }
  return {
    handled: true,
    effects: [
      { type: "emit_user_text", text: input },
      {
        type: "submit_prompt",
        prompt: `Rotate secrets for service ${subparts[1]} in stack ${subparts[0]}`,
      },
    ],
  };
}

function handleModel(input: string, parts: string[], ctx: SlashRouterContext): SlashRouteResult {
  const modelArg = parts.slice(1).join(" ").trim();
  if (!modelArg) {
    return {
      handled: true,
      effects: [{ type: "emit_user_text", text: input }, { type: "open_model_picker" }],
    };
  }
  const parsed = parseProviderModel(modelArg, ctx.activeProviderName);
  if (!parsed || !/[a-zA-Z0-9]/.test(parsed.model)) {
    return {
      handled: true,
      effects: [
        { type: "emit_user_text", text: input },
        { type: "emit_error", message: "Invalid model. Use /model <id> or /model <provider>/<id>" },
      ],
    };
  }
  return {
    handled: true,
    effects: [
      { type: "emit_user_text", text: input },
      { type: "set_model", provider: parsed.provider, model: parsed.model },
      {
        type: "emit_assistant_text",
        delta: `Model set to ${parsed.model} (${parsed.provider})`,
      },
    ],
  };
}

function handleLogs(input: string, parts: string[]): SlashRouteResult {
  const logParts = parts.slice(1).filter(Boolean);
  const stackName = logParts[0];
  const service = logParts[1];
  if (!stackName) {
    return {
      handled: true,
      effects: [
        { type: "emit_user_text", text: input },
        { type: "emit_error", message: "Usage: /logs <stack> [service]" },
      ],
    };
  }
  return {
    handled: true,
    effects: [
      {
        type: "start_log_pane",
        stackName,
        ...(service ? { service } : {}),
      },
    ],
  };
}

function handleDetails(ctx: SlashRouterContext): SlashRouteResult {
  if (!ctx.hasLatestTool) {
    return { handled: true, effects: [{ type: "emit_error", message: "No tool activity yet." }] };
  }
  return { handled: true, effects: [{ type: "toggle_details" }] };
}

function handleQueueRemove(parts: string[]): SlashRouteResult {
  const idx = Number(parts[2]);
  if (Number.isInteger(idx) && idx > 0) {
    return { handled: true, effects: [{ type: "queue_remove", index: idx - 1 }] };
  }
  return {
    handled: true,
    effects: [{ type: "emit_error", message: "Usage: /queue resume | clear | remove <index>" }],
  };
}

export function resolveSlashKey(parts: string[]): HandlerKey | null {
  const lowered = parts.map((p) => p.toLowerCase());
  for (let len = Math.min(3, lowered.length); len >= 1; len--) {
    const candidate = lowered.slice(0, len).join(" ");
    if ((HANDLER_KEYS as readonly string[]).includes(candidate)) {
      return candidate as HandlerKey;
    }
  }
  return null;
}

export async function routeSlashCommand(
  input: string,
  ctx: SlashRouterContext,
): Promise<SlashRouteResult> {
  const parts = input.trim().split(/\s+/);
  const key = resolveSlashKey(parts);
  if (!key) {
    const cmd = parts[0]?.toLowerCase() ?? input;
    return {
      handled: true,
      effects: [
        { type: "emit_user_text", text: input },
        { type: "emit_error", message: `Unknown slash command: ${cmd}. Try /help.` },
      ],
    };
  }

  switch (key) {
    case "/help":
      return handleHelp(input);
    case "/clear":
      return { handled: true, effects: [{ type: "clear_session" }] };
    case "/exit":
      return { handled: true, effects: [{ type: "exit" }] };
    case "/stacks":
      return handleStacks(input, ctx);
    case "/yaml":
      return handleYaml(input, parts, ctx);
    case "/secrets list":
      return handleSecretsList(input, parts, ctx);
    case "/secrets rotate":
      return handleSecretsRotate(input, parts);
    case "/secrets":
      return handleSecrets(input);
    case "/status":
      return handleStatus(input, parts);
    case "/destroy all":
      return handleDestroyAll(input);
    case "/destroy":
      return handleDestroy(input, parts);
    case "/connect":
      return {
        handled: true,
        effects: [{ type: "emit_user_text", text: input }, { type: "open_provider_connect" }],
      };
    case "/models":
      return {
        handled: true,
        effects: [{ type: "emit_user_text", text: input }, { type: "open_model_picker" }],
      };
    case "/model":
      return handleModel(input, parts, ctx);
    case "/resume":
      return {
        handled: true,
        effects: [
          {
            type: "load_session",
            ...(parts[1] ? { sessionId: parts.slice(1).join(" ").trim() } : {}),
          },
        ],
      };
    case "/logs":
      return handleLogs(input, parts);
    case "/cancel":
      return { handled: true, effects: [{ type: "cancel_current" }] };
    case "/details":
      return handleDetails(ctx);
    case "/queue resume":
      return { handled: true, effects: [{ type: "queue_resume" }] };
    case "/queue clear":
      return { handled: true, effects: [{ type: "queue_clear" }] };
    case "/queue remove":
      return handleQueueRemove(parts);
    default:
      return {
        handled: true,
        effects: [
          { type: "emit_user_text", text: input },
          { type: "emit_error", message: `Unknown slash command: ${key}. Try /help.` },
        ],
      };
  }
}
