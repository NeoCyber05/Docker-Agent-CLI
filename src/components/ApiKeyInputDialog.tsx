import { Box, Text, useInput } from "ink";
import type React from "react";
import { useRef, useState } from "react";
import type { ApiKeyProviderName } from "src/secrets/apiKeyStore";

export function ApiKeyInputDialog({
  provider,
  envVarName,
  onSubmit,
  onCancel,
}: {
  provider: ApiKeyProviderName;
  envVarName: string;
  onSubmit: (value: string) => void;
  onCancel: () => void;
}): React.ReactElement {
  const [buf, setBuf] = useState("");
  const [error, setError] = useState("");
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
        onCancel();
      }
      return;
    }
    if (key.return) {
      const value = buf.trim();
      if (!value) {
        setError("API key cannot be empty");
        return;
      }
      if (!answeredRef.current) {
        answeredRef.current = true;
        onSubmit(value);
      }
      return;
    }
    if (key.backspace || key.delete) {
      setError("");
      setBuf((s) => s.slice(0, -1));
      return;
    }
    if (input && !key.ctrl && !key.meta) {
      setError("");
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
        Save API key for {provider}
      </Text>
      <Text dimColor>Stored persistently. The value is never printed back.</Text>
      <Box marginTop={1}>
        <Text bold>
          {envVarName}: <Text color="yellow">{masked}</Text>
        </Text>
      </Box>
      {error && (
        <Box marginTop={1}>
          <Text color="red">{error}</Text>
        </Box>
      )}
      <Box marginTop={1}>
        <Text dimColor>Enter to save, Esc to cancel</Text>
      </Box>
    </Box>
  );
}
