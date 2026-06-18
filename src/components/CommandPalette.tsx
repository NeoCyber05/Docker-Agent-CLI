import { Box, Text, useInput } from "ink";
import type React from "react";
import { useState } from "react";
import type { Command } from "src/commands/registry";

export function CommandPalette({
  commands,
  onSelect,
  onClose,
}: {
  commands: Command[];
  onSelect: (command: Command) => void;
  onClose: () => void;
}): React.ReactElement {
  const [selected, setSelected] = useState(0);

  useInput((_input, key) => {
    if (key.escape) {
      onClose();
      return;
    }
    if (key.upArrow) {
      setSelected((i) => (i <= 0 ? commands.length - 1 : i - 1));
      return;
    }
    if (key.downArrow) {
      setSelected((i) => (i + 1) % commands.length);
      return;
    }
    if (key.return) {
      const cmd = commands[selected];
      if (cmd) onSelect(cmd);
      return;
    }
  });

  return (
    <Box flexDirection="column" borderStyle="single" paddingX={1}>
      <Text bold>Command Palette</Text>
      {commands.map((cmd, i) => (
        <Box key={cmd.id} flexDirection="row" gap={1}>
          {i === selected ? <Text color="cyan">{">"}</Text> : <Text> </Text>}
          <Text bold>{cmd.title}</Text>
          <Text dimColor>{cmd.description}</Text>
          {cmd.shortcut && <Text dimColor>({cmd.shortcut})</Text>}
        </Box>
      ))}
    </Box>
  );
}
