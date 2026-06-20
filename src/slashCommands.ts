export interface SlashCommandSuggestion {
  usage: string;
  description: string;
  insertText: string;
}

export const SLASH_COMMANDS: readonly SlashCommandSuggestion[] = [
  {
    usage: "/help",
    description: "Show slash command help",
    insertText: "/help",
  },
  {
    usage: "/clear",
    description: "Clear chat history and session state",
    insertText: "/clear",
  },
  {
    usage: "/exit",
    description: "Exit docker-agent",
    insertText: "/exit",
  },
  {
    usage: "/stacks",
    description: "List managed stacks",
    insertText: "/stacks",
  },
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
  {
    usage: "/destroy <stack>",
    description: "Destroy one stack",
    insertText: "/destroy ",
  },
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
  {
    usage: "/models",
    description: "Browse and select a model",
    insertText: "/models",
  },
  {
    usage: "/model <id>",
    description: "Set model override (or provider/model)",
    insertText: "/model ",
  },
  {
    usage: "/yaml <stack>",
    description: "Show stack YAML",
    insertText: "/yaml ",
  },
  {
    usage: "/resume",
    description: "Resume the most recent session",
    insertText: "/resume",
  },
  {
    usage: "/resume <id>",
    description: "Resume a specific session by id",
    insertText: "/resume ",
  },
  {
    usage: "/cancel",
    description: "Cancel the current turn",
    insertText: "/cancel",
  },
  {
    usage: "/details",
    description: "Open details for the latest tool",
    insertText: "/details",
  },
  {
    usage: "/queue resume",
    description: "Resume processing the queue",
    insertText: "/queue resume",
  },
  {
    usage: "/queue clear",
    description: "Clear the queued turns",
    insertText: "/queue clear",
  },
  {
    usage: "/queue remove <index>",
    description: "Remove a queued turn by index",
    insertText: "/queue remove ",
  },
];

export function getSlashCommandSuggestions(input: string): SlashCommandSuggestion[] {
  const query = input.trimStart().toLowerCase();
  if (!query.startsWith("/") || query.includes("\n")) return [];
  if (query.endsWith(" ")) return [];
  return SLASH_COMMANDS.filter(
    (command) =>
      command.usage.toLowerCase().startsWith(query) ||
      command.insertText.trimEnd().toLowerCase().startsWith(query),
  );
}

export function formatSlashHelp(): string {
  return [
    "Supported slash commands:",
    ...SLASH_COMMANDS.map((command) => `- ${command.usage}: ${command.description}`),
  ].join("\n");
}
