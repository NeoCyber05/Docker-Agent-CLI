import { Box, Text, useInput } from "ink";
import type React from "react";
import { useRef, useState } from "react";
import type { PermissionResponse } from "src/types/permissions";

export function TypedConfirmDialog({
  phrase,
  reason,
  onAnswer,
}: {
  phrase: string;
  reason: string;
  onAnswer: (r: PermissionResponse) => void;
}): React.ReactElement {
  const [text, setText] = useState("");
  const answeredRef = useRef(false);

  useInput((input, key) => {
    if (key.return) {
      if (!answeredRef.current) {
        answeredRef.current = true;
        if (text === phrase) {
          onAnswer({ kind: "typed_confirm_value", value: text });
        } else {
          onAnswer({ kind: "deny" });
        }
      }
      return;
    }
    if (key.backspace || key.delete) {
      setText((s) => s.slice(0, -1));
      return;
    }
    if (input && !key.ctrl && !key.meta) setText((s) => s + input);
  });

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="red" paddingX={1} marginY={1} overflowX="hidden">
      <Text bold color="red">
        Type "{phrase}" to confirm
      </Text>
      <Text>{reason}</Text>
      <Box marginTop={1}>
        <Text bold>{`> ${text}`}</Text>
      </Box>
    </Box>
  );
}
