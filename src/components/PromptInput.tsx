import { Box, Text, useInput } from "ink";
import type React from "react";
import { useState, useRef } from "react";
import { type SlashCommandSuggestion, getSlashCommandSuggestions } from "src/slashCommands";

function shouldCompleteSuggestion(text: string, suggestion: SlashCommandSuggestion): boolean {
  return text.trimEnd().toLowerCase() !== suggestion.insertText.trimEnd().toLowerCase();
}

export function PromptInput({
  onSubmit,
}: {
  onSubmit: (text: string) => void;
}): React.ReactElement {
  const [text, setText] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const [historyIdx, setHistoryIdx] = useState(-1);
  const [draft, setDraft] = useState("");
  const [suggestionIdx, setSuggestionIdx] = useState(0);
  const suggestions = getSlashCommandSuggestions(text);
  const selectedSuggestion = suggestions[Math.min(suggestionIdx, suggestions.length - 1)];

  // Refs to handle duplicate paste on Windows Terminal
  const justPastedRef = useRef(false);
  const pastedCharsRef = useRef<string[]>([]);
  const pastedIndexRef = useRef(0);
  const lastPasteTimeRef = useRef(0);

  useInput((input, key) => {
    const acceptSuggestion = (suggestion: SlashCommandSuggestion) => {
      setHistoryIdx(-1);
      setDraft("");
      setSuggestionIdx(0);
      setText(suggestion.insertText);
    };

    // Multi-line support: Alt+Enter (key.meta && key.return)
    if (key.return) {
      if (key.meta || key.ctrl) {
        setSuggestionIdx(0);
        setText((s) => `${s}\n`);
        return;
      }
      if (selectedSuggestion && shouldCompleteSuggestion(text, selectedSuggestion)) {
        acceptSuggestion(selectedSuggestion);
        return;
      }
      const t = text.trim();
      if (t) {
        setHistory((prev) => [...prev, text]);
        setHistoryIdx(-1);
        setDraft("");
        onSubmit(t);
      }
      setSuggestionIdx(0);
      setText("");
      return;
    }

    // Command History: Up arrow
    if (key.upArrow) {
      if (suggestions.length > 0) {
        setSuggestionIdx((idx) => (idx <= 0 ? suggestions.length - 1 : idx - 1));
        return;
      }
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
      setSuggestionIdx(0);
      setText(history[nextIdx] ?? "");
      return;
    }

    // Command History: Down arrow
    if (key.downArrow) {
      if (suggestions.length > 0) {
        setSuggestionIdx((idx) => (idx + 1) % suggestions.length);
        return;
      }
      if (historyIdx === -1) return;
      const nextIdx = historyIdx + 1;
      if (nextIdx >= history.length) {
        setHistoryIdx(-1);
        setSuggestionIdx(0);
        setText(draft);
      } else {
        setHistoryIdx(nextIdx);
        setSuggestionIdx(0);
        setText(history[nextIdx] ?? "");
      }
      return;
    }

    if ((key.tab || input === "\t") && selectedSuggestion) {
      acceptSuggestion(selectedSuggestion);
      return;
    }

    if (key.backspace || key.delete) {
      setSuggestionIdx(0);
      setText((s) => s.slice(0, -1));
      return;
    }

    if (input && !key.ctrl && !key.meta) {
      setSuggestionIdx(0);
      const now = Date.now();

      // If it is a paste chunk (length > 1)
      if (input.length > 1) {
        setText((s) => s + input);
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

      setText((s) => s + input);
    }
  });

  return (
    <Box flexDirection="column" marginLeft={1} marginTop={1}>
      <Box>
        <Text color="cyan" bold>
          ▶{" "}
        </Text>
        <Text>{text}</Text>
        <Text color="cyan" bold>
          █
        </Text>
      </Box>
      <Box marginTop={0}>
        <Text dimColor>(Alt+Enter for newline, Up/Down for history)</Text>
      </Box>
      {suggestions.length > 0 && (
        <Box flexDirection="column" marginTop={1} paddingLeft={2}>
          {suggestions.map((suggestion, idx) => (
            <Box key={suggestion.usage}>
              <Text {...(idx === suggestionIdx ? { color: "cyan" as const } : {})}>
                {idx === suggestionIdx ? "> " : "  "}
                {suggestion.usage}
              </Text>
              <Text dimColor> - {suggestion.description}</Text>
            </Box>
          ))}
          <Box>
            <Text dimColor>Tab to complete, Enter to accept prefix</Text>
          </Box>
        </Box>
      )}
    </Box>
  );
}
