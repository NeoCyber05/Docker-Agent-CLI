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

  // Refs to handle duplicate paste on Windows Terminal
  const justPastedRef = useRef(false);
  const pastedCharsRef = useRef<string[]>([]);
  const pastedIndexRef = useRef(0);
  const lastPasteTimeRef = useRef(0);

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
    if (input && !key.ctrl && !key.meta) {
      const now = Date.now();

      // If it is a paste chunk (length > 1)
      if (input.length > 1) {
        setBuf((s) => s + input);
        justPastedRef.current = true;
        pastedCharsRef.current = Array.from(input);
        pastedIndexRef.current = 0;
        lastPasteTimeRef.current = now;
        return;
      }

      // If in paste filtering state and receiving simulated single characters
      if (justPastedRef.current) {
        const timeDiff = now - lastPasteTimeRef.current;
        // Windows Terminal simulates key presses extremely fast (usually < 10ms)
        if (timeDiff > 50) {
          justPastedRef.current = false;
        } else {
          const expectedChar = pastedCharsRef.current[pastedIndexRef.current];
          if (input === expectedChar) {
            pastedIndexRef.current++;
            lastPasteTimeRef.current = now;
            if (pastedIndexRef.current >= pastedCharsRef.current.length) {
              justPastedRef.current = false;
            }
            return;
          } else {
            justPastedRef.current = false;
          }
        }
      }

      setBuf((s) => s + input);
    }
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
