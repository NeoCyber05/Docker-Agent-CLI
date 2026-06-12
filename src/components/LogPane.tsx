import { Box, Text, useInput } from "ink";
import type React from "react";

export const MAX_VISIBLE_LINES = 200;

export interface LogPaneProps {
  stackName: string;
  service?: string;
  lines: string[];
  onClose: () => void;
}

export function LogPane(props: LogPaneProps): React.ReactElement {
  useInput((_input, key) => {
    if (key.escape) props.onClose();
  });

  const visible = props.lines.slice(-MAX_VISIBLE_LINES);
  const title = props.service
    ? `Live logs: ${props.stackName} / ${props.service}`
    : `Live logs: ${props.stackName}`;

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="cyan"
      paddingX={1}
      marginY={1}
      overflowX="hidden"
    >
      <Text bold color="cyan">
        {title}
      </Text>
      <Box flexDirection="column" marginTop={1}>
        {visible.length === 0 ? (
          <Text dimColor>no running containers / waiting for output...</Text>
        ) : (
          visible.map((line, i) => (
            // Lines may repeat; index is a stable key within a single render frame.
            <Text key={`${i}-${line}`} dimColor>
              {line.replace(/\n$/, "")}
            </Text>
          ))
        )}
      </Box>
      <Box marginTop={1}>
        <Text dimColor>Esc to stop</Text>
      </Box>
    </Box>
  );
}
