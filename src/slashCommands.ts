import { SLASH_COMMAND_DEFS } from "src/slashRouter";

export interface SlashCommandSuggestion {
  usage: string;
  description: string;
  insertText: string;
}

export const SLASH_COMMANDS: readonly SlashCommandSuggestion[] = SLASH_COMMAND_DEFS;

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

export { formatSlashHelp } from "src/slashRouter";
