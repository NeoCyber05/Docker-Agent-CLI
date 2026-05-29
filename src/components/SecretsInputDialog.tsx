import { Box, Text, useInput } from "ink";
import type React from "react";
import { useRef, useState } from "react";
import type { PermissionResponse } from "src/types/permissions";

export function SecretsInputDialog({
  service,
  keys,
  reason,
  onAnswer,
}: {
  service: string;
  keys: string[];
  reason: string;
  onAnswer: (r: PermissionResponse) => void;
}): React.ReactElement {
  const [idx, setIdx] = useState(0);
  const [values, setValues] = useState<Record<string, string>>({});
  const [buf, setBuf] = useState("");
  const currentKey = keys[idx] as string;
  const answeredRef = useRef(false);

  useInput((input, key) => {
    if (key.escape) {
      if (!answeredRef.current) {
        answeredRef.current = true;
        onAnswer({ kind: "deny" });
      }
      return;
    }
    if (key.return) {
      const next = { ...values, [currentKey]: buf };
      setValues(next);
      setBuf("");
      if (idx + 1 >= keys.length) {
        if (!answeredRef.current) {
          answeredRef.current = true;
          onAnswer({ kind: "secrets_input_values", values: next });
        }
      } else {
        setIdx(idx + 1);
      }
      return;
    }
    if (key.backspace || key.delete) {
      setBuf((s) => s.slice(0, -1));
      return;
    }
    if (input && !key.ctrl && !key.meta) setBuf((s) => s + input);
  });

  const masked = buf.replace(/./g, "*");
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="magenta" paddingX={1} marginY={1}>
      <Text bold color="magenta">
        Service {service} needs required env values
      </Text>
      <Text dimColor>{reason}</Text>
      <Box marginTop={1}>
        <Text bold>
          {currentKey}: <Text color="yellow">{masked}</Text>
        </Text>
      </Box>
      <Box marginTop={1}>
        <Text dimColor>
          {idx + 1}/{keys.length} — Enter to submit, Esc to cancel
        </Text>
      </Box>
    </Box>
  );
}
