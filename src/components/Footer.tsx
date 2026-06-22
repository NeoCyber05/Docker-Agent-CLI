import { Box, Text } from "ink";
import type React from "react";

export function Footer({
  usage,
  sessionId,
  activeTool,
  queueCount,
}: {
  usage: { inputTokens: number; outputTokens: number };
  sessionId?: string | undefined;
  activeTool?: string | undefined;
  queueCount?: number | undefined;
}): React.ReactElement {
  return (
    <Box paddingX={1} flexDirection="row" gap={2}>
      {sessionId && <Text dimColor>session: {sessionId}</Text>}
      <Text dimColor>
        tokens in/out: {usage.inputTokens}/{usage.outputTokens}
      </Text>
      {activeTool && (
        <Text dimColor color="yellow">
          ● {activeTool} (Ctrl+O details)
        </Text>
      )}
      {queueCount !== undefined && queueCount > 0 && <Text dimColor>queue: {queueCount}</Text>}
    </Box>
  );
}
