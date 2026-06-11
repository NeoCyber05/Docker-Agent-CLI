import { Box, Text, useInput } from "ink";
import type React from "react";
import { useState } from "react";

const PAGE_SIZE = 10;

export function ModelPickerDialog({
  models,
  current,
  onSelect,
  onCancel,
}: {
  models: string[];
  current?: string;
  onSelect: (model: string) => void;
  onCancel: () => void;
}): React.ReactElement {
  const initial = Math.max(
    0,
    models.findIndex((m) => m === current),
  );
  const [index, setIndex] = useState(initial);

  useInput((_char, key) => {
    if (key.upArrow) {
      setIndex((i) => (i - 1 + models.length) % models.length);
    } else if (key.downArrow) {
      setIndex((i) => (i + 1) % models.length);
    } else if (key.return) {
      const choice = models[index];
      if (choice) onSelect(choice);
    } else if (key.escape) {
      onCancel();
    }
  });

  // Keep the highlighted row inside a sliding window for long lists.
  const start = Math.min(
    Math.max(0, index - Math.floor(PAGE_SIZE / 2)),
    Math.max(0, models.length - PAGE_SIZE),
  );
  const visible = models.slice(start, start + PAGE_SIZE);

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1} marginY={1} overflowX="hidden">
      <Text bold color="cyan">
        Select a model ({models.length} available)
      </Text>
      {start > 0 && <Text dimColor> ↑ more…</Text>}
      {visible.map((model, i) => {
        const realIndex = start + i;
        const selected = realIndex === index;
        const isCurrent = model === current;
        return (
          <Text key={model} {...(selected ? { color: "black", backgroundColor: "cyan" } : {})}>
            {selected ? "❯ " : "  "}
            {model}
            {isCurrent ? " (current)" : ""}
          </Text>
        );
      })}
      {start + PAGE_SIZE < models.length && <Text dimColor> ↓ more…</Text>}
      <Box marginTop={1}>
        <Text bold>[↑/↓] navigate [Enter] select [Esc] cancel</Text>
      </Box>
    </Box>
  );
}
