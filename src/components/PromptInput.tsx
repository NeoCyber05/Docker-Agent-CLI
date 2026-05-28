import { Box, Text, useInput } from "ink";
import type React from "react";
import { useState } from "react";

export function PromptInput({
  onSubmit,
}: {
  onSubmit: (text: string) => void;
}): React.ReactElement {
  const [text, setText] = useState("");
  useInput((input, key) => {
    if (key.return) {
      const t = text.trim();
      if (t) onSubmit(t);
      setText("");
      return;
    }
    if (key.backspace || key.delete) {
      setText((s) => s.slice(0, -1));
      return;
    }
    if (input && !key.ctrl && !key.meta) setText((s) => s + input);
  });
  return (
    <Box>
      <Text color="green">{"> "}</Text>
      <Text>{text}</Text>
      <Text>{"█"}</Text>
    </Box>
  );
}
