import { Box, Text, useInput } from "ink";
import type React from "react";
import { useRef, useState } from "react";
import { type SlashCommandSuggestion, getSlashCommandSuggestions } from "src/slashCommands";

function shouldCompleteSuggestion(text: string, suggestion: SlashCommandSuggestion): boolean {
  return text.trimEnd().toLowerCase() !== suggestion.insertText.trimEnd().toLowerCase();
}

// Counts user-perceived characters, treating Unicode combining marks (\p{M})
// as part of the preceding base character. A single Vietnamese keystroke
// (e.g. "ế" delivered as base + combining marks) counts as 1, not 3.
function baseCharCount(text: string): number {
  let count = 0;
  for (const ch of text) {
    if (!/\p{M}/u.test(ch)) count++;
  }
  return count;
}

// Splits a string into grapheme-like clusters, grouping combining marks with
// their preceding base character. Used to align the Windows Terminal
// duplicate-paste filter with multi-code-point graphemes.
function splitGraphemes(text: string): string[] {
  const clusters: string[] = [];
  for (const ch of text) {
    if (/\p{M}/u.test(ch) && clusters.length > 0) {
      clusters[clusters.length - 1] += ch;
    } else {
      clusters.push(ch);
    }
  }
  return clusters;
}

// A genuine paste contains a newline or more than one base character.
// A single typed character — even a Vietnamese grapheme spanning several
// code points — is NOT a paste and must bypass the dedup heuristic.
function isPasteChunk(text: string): boolean {
  if (/[\r\n]/.test(text)) return true;
  return baseCharCount(text) > 1;
}

const DEL = "\u007f";
const BS = "\u0008";

// The Vietnamese Telex IME rewrites a character by emitting a DEL (0x7f) or
// backspace (0x08) control character immediately followed by the recomposed
// text (e.g. typing "dd" arrives as "\u007fđ", "chay"→"chạy" arrives as a
// "\u007f\u007f" chunk then "ạy"). Ink only surfaces a *lone* control byte as
// key.delete; when it is bundled with other characters it lands here as raw
// input. Apply each control char as a backspace and insert the rest in order.
function hasEditingControl(text: string): boolean {
  return text.includes(DEL) || text.includes(BS);
}

function applyInlineEdits(current: string, input: string): string {
  let result = current;
  for (const ch of input) {
    if (ch === DEL || ch === BS) {
      result = result.slice(0, -1);
    } else if (ch >= " ") {
      result += ch;
    }
  }
  return result;
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
      // Normalize to NFC so Vietnamese combining sequences (e.g. "e" + ◌̂ + ◌́)
      // collapse into a single precomposed code point where possible.
      const normalized = input.normalize("NFC");
      const now = Date.now();

      // IME backspace-and-rewrite: DEL/BS control chars embedded in the input
      // string (Ink does not surface these as key.delete when bundled). Apply
      // them as backspaces so Telex character conversion works correctly.
      if (hasEditingControl(normalized)) {
        justPastedRef.current = false;
        setText((s) => applyInlineEdits(s, normalized));
        return;
      }

      // Genuine paste chunk (multiple base characters or a newline).
      // Single typed graphemes fall through to the normal append path even if
      // they span multiple code points (combining diacritics).
      if (isPasteChunk(normalized)) {
        setText((s) => s + normalized);
        justPastedRef.current = true;
        pastedCharsRef.current = splitGraphemes(normalized);
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
          if (normalized === expectedChar) {
            pastedIndexRef.current++;
            lastPasteTimeRef.current = now;
            if (pastedIndexRef.current >= pastedCharsRef.current.length) {
              justPastedRef.current = false;
            }
            return;
          }
          justPastedRef.current = false;
        }
      }

      setText((s) => s + normalized);
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
