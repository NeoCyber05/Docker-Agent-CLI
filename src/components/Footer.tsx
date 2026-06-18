import { Box, Text } from "ink";
import type React from "react";

export function Footer({
  usage,
  activeTool,
  queueCount,
}: {
  usage: { inputTokens: number; outputTokens: number };
  activeTool?: string | undefined;
  queueCount?: number | undefined;
}): React.ReactElement {
  return (
    <Box paddingX={1} flexDirection="row" gap={2}>
      <Text dimColor>
        tokens in/out: {usage.inputTokens}/{usage.outputTokens}
      </Text>
      {activeTool && (
        <Text dimColor color="yellow">
          ● {activeTool}
        </Text>
      )}
      {queueCount !== undefined && queueCount > 0 && <Text dimColor>queue: {queueCount}</Text>}
    </Box>
  );
}
