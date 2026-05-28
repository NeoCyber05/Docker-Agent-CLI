import { Box, Text, useInput } from "ink";
import type React from "react";
import { useState } from "react";

export function PromptInput({
  onSubmit,
}: {
  onSubmit: (text: string) => void;
}): React.ReactElement {
  const [text, setText] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const [historyIdx, setHistoryIdx] = useState(-1);
  const [draft, setDraft] = useState("");

  useInput((input, key) => {
    // Multi-line support: Alt+Enter (key.meta && key.return)
    if (key.return) {
      if (key.meta || key.ctrl) {
        setText((s) => s + "\n");
        return;
      }
      const t = text.trim();
      if (t) {
        setHistory((prev) => [...prev, text]);
        setHistoryIdx(-1);
        setDraft("");
        onSubmit(t);
      }
      setText("");
      return;
    }

    // Command History: Up arrow
    if (key.upArrow) {
      if (history.length === 0) return;
      let nextIdx = historyIdx;
      if (historyIdx === -1) {
        setDraft(text);
        nextIdx = history.length - 1;
      } else if (historyIdx > 0) {
        nextIdx = historyIdx - 1;
      } else {
        return; // already at oldest
      }
      setHistoryIdx(nextIdx);
      setText(history[nextIdx] ?? "");
      return;
    }

    // Command History: Down arrow
    if (key.downArrow) {
      if (historyIdx === -1) return;
      const nextIdx = historyIdx + 1;
      if (nextIdx >= history.length) {
        setHistoryIdx(-1);
        setText(draft);
      } else {
        setHistoryIdx(nextIdx);
        setText(history[nextIdx] ?? "");
      }
      return;
    }

    if (key.backspace || key.delete) {
      setText((s) => s.slice(0, -1));
      return;
    }

    if (input && !key.ctrl && !key.meta) {
      setText((s) => s + input);
    }
  });

  return (
    <Box flexDirection="column" marginLeft={1} marginTop={1}>
      <Box>
        <Text color="cyan" bold>▶ </Text>
        <Text>{text}</Text>
        <Text color="cyan" bold>█</Text>
      </Box>
      <Box marginTop={0}>
        <Text dimColor>
          (Alt+Enter for newline, Up/Down for history)
        </Text>
      </Box>
    </Box>
  );
}

