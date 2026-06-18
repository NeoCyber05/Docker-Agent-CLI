import { Box, Text, useInput } from "ink";
import type React from "react";
import { useRef } from "react";

export function OllamaSetupDialog({
  host,
  onRetry,
  onCancel,
}: {
  host: string;
  onRetry: () => void;
  onCancel: () => void;
}): React.ReactElement {
  const answeredRef = useRef(false);

  useInput((_char, key) => {
    if (key.escape) {
      if (!answeredRef.current) {
        answeredRef.current = true;
        onCancel();
      }
      return;
    }
    if (key.return) {
      if (!answeredRef.current) {
        answeredRef.current = true;
        onRetry();
      }
    }
  });

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="yellow"
      paddingX={1}
      marginY={1}
      overflowX="hidden"
    >
      <Text bold color="yellow">
        Connect Ollama
      </Text>
      <Box marginTop={1} flexDirection="column">
        <Text>Could not reach {host}.</Text>
        <Text>Run: ollama serve</Text>
        <Text>Or set OLLAMA_HOST</Text>
      </Box>
      <Box marginTop={1}>
        <Text dimColor>[Enter] retry [Esc] cancel</Text>
      </Box>
    </Box>
  );
}
