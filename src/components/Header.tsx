import { Box, Text } from "ink";
import type React from "react";

export function Header({ provider }: { provider: string }): React.ReactElement {
  return (
    <Box paddingX={1} borderStyle="single" borderColor="cyan">
      <Text>
        docker-agent · provider: <Text color="yellow">{provider}</Text>
      </Text>
    </Box>
  );
}
