import { Box, Text, useInput } from "ink";
import type React from "react";
import { useState } from "react";

export function QueuePanel({
  queue,
  onRemove,
  onClear,
  onClose,
}: {
  queue: string[];
  onRemove: (index: number) => void;
  onClear: () => void;
  onClose: () => void;
}): React.ReactElement {
  const [selected, setSelected] = useState(0);

  useInput((_input, key) => {
    if (key.escape) {
      onClose();
      return;
    }
    if (key.upArrow) {
      setSelected((i) => (i <= 0 ? queue.length - 1 : i - 1));
      return;
    }
    if (key.downArrow) {
      setSelected((i) => (i + 1) % queue.length);
      return;
    }
    if (_input.toLowerCase() === "d" && queue.length > 0) {
      onRemove(selected);
      return;
    }
    if (_input.toLowerCase() === "c") {
      onClear();
      return;
    }
  });

  return (
    <Box flexDirection="column" borderStyle="single" paddingX={1}>
      <Text bold>Queue ({queue.length})</Text>
      {queue.length === 0 && <Text dimColor>Empty</Text>}
      {queue.map((item, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: queue items are stable strings; index is acceptable here
        <Box key={`q-${i}`} flexDirection="row" gap={1}>
          {i === selected ? <Text color="cyan">{">"}</Text> : <Text> </Text>}
          <Text>
            {i + 1}. {item}
          </Text>
        </Box>
      ))}
      <Text dimColor>Up/Down select | d remove | c clear | Esc close</Text>
    </Box>
  );
}
