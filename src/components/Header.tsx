import { Box, Text } from "ink";
import type React from "react";

export function Header({
  provider,
  model,
}: {
  provider: string;
  model?: string;
}): React.ReactElement {
  return (
    <Box paddingX={1} borderStyle="single" borderColor="cyan">
      <Text>
        docker-agent | provider: <Text color="yellow">{provider}</Text>
        {" | "}
        model: <Text color="yellow">{model ?? "default"}</Text>
      </Text>
    </Box>
  );
}
