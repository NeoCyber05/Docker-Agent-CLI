import { Box, Text, useInput } from "ink";
import type React from "react";
import { useRef } from "react";
import type { PermissionResponse } from "src/types/permissions";

export function PermissionDialog({
  tool,
  input,
  onAnswer,
}: {
  tool: string;
  input: unknown;
  onAnswer: (r: PermissionResponse) => void;
}): React.ReactElement {
  const answeredRef = useRef(false);

  useInput((char) => {
    const k = char.toLowerCase();
    if (k === "y") {
      if (!answeredRef.current) {
        answeredRef.current = true;
        onAnswer({ kind: "approve" });
      }
    }
    if (k === "n") {
      if (!answeredRef.current) {
        answeredRef.current = true;
        onAnswer({ kind: "deny" });
      }
    }
    if (k === "a") {
      if (!answeredRef.current) {
        answeredRef.current = true;
        onAnswer({ kind: "always_allow_in_session" });
      }
    }
  });

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="magenta" paddingX={1} marginY={1} overflowX="hidden">
      <Text bold color="magenta">
        Permission required
      </Text>
      <Text>
        Tool:{" "}
        <Text color="cyan" bold>
          {tool}
        </Text>
      </Text>
      <Text>
        Input: <Text dimColor>{JSON.stringify(input)}</Text>
      </Text>
      <Box marginTop={1}>
        <Text bold>[y] approve [n] deny [a] always for this session</Text>
      </Box>
    </Box>
  );
}
