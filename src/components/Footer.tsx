import { Box, Text } from "ink";
import type React from "react";

export function Footer({
  usage,
}: {
  usage: { inputTokens: number; outputTokens: number };
}): React.ReactElement {
  return (
    <Box paddingX={1}>
      <Text dimColor>
        tokens in/out: {usage.inputTokens}/{usage.outputTokens}
      </Text>
    </Box>
  );
}
