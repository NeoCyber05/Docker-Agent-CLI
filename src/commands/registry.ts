import { SLASH_COMMAND_DEFS } from "src/slashRouter";

export interface Command {
  id: string;
  title: string;
  description: string;
  shortcut?: string;
  insertText?: string;
  action?: () => void;
}

export class CommandRegistry {
  private commands: Command[] = [];

  register(command: Command): void {
    const index = this.commands.findIndex((existing) => existing.id === command.id);
    if (index === -1) this.commands.push(command);
    else this.commands[index] = command;
  }

  getAll(): Command[] {
    return [...this.commands];
  }

  findByShortcut(shortcut: string): Command | undefined {
    return this.commands.find((c) => c.shortcut === shortcut);
  }

  findById(id: string): Command | undefined {
    return this.commands.find((c) => c.id === id);
  }
}

export function createDefaultRegistry(): CommandRegistry {
  const registry = new CommandRegistry();
  for (const command of SLASH_COMMAND_DEFS) {
    const id = command.usage
      .slice(1)
      .replace(/[<>]/g, "")
      .replace(/\s+/g, "-")
      .replace(/[^a-z0-9-]/gi, "")
      .toLowerCase();
    registry.register({
      id,
      title: command.usage,
      description: command.description,
      insertText: command.insertText,
    });
  }
  return registry;
}
