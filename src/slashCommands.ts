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
    usage: "/quit",
    description: "Exit docker-agent",
    insertText: "/quit",
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
    usage: "/provider <gemini|openai|ollama>",
    description: "Switch provider for this session",
    insertText: "/provider ",
  },
  {
    usage: "/apikey set openai",
    description: "Save OpenAI API key",
    insertText: "/apikey set openai",
  },
  {
    usage: "/apikey set gemini",
    description: "Save Gemini API key",
    insertText: "/apikey set gemini",
  },
  {
    usage: "/apikey status",
    description: "Show API key status per provider",
    insertText: "/apikey status",
  },
  {
    usage: "/models",
    description: "List available models and pick one quickly",
    insertText: "/models",
  },
  {
    usage: "/model <id>",
    description: "Set model override for this session",
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
