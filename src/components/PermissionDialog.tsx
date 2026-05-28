import { Box, Text, useInput } from "ink";
import type React from "react";
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
  useInput((input) => {
    const k = input.toLowerCase();
    if (k === "y") onAnswer({ kind: "approve" });
    if (k === "n") onAnswer({ kind: "deny" });
    if (k === "a") onAnswer({ kind: "always_allow_in_session" });
  });
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="magenta" paddingX={1}>
      <Text bold>Permission required</Text>
      <Text>Tool: {tool}</Text>
      <Text>Input: {JSON.stringify(input)}</Text>
      <Text>[y] approve [n] deny [a] always for this session</Text>
    </Box>
  );
}
