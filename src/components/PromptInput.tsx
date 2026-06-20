import { Box, Text, useInput } from "ink";
import type React from "react";
import { useEffect, useRef, useState } from "react";
import { type SlashCommandSuggestion, getSlashCommandSuggestions } from "src/slashCommands";
import type { InteractionPhase } from "src/ui/interactionState";

function shouldCompleteSuggestion(text: string, suggestion: SlashCommandSuggestion): boolean {
  return text.trimEnd().toLowerCase() !== suggestion.insertText.trimEnd().toLowerCase();
}

function insertAt(current: string, pos: number, insertion: string): string {
  return current.slice(0, pos) + insertion + current.slice(pos);
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
  phase = "idle",
  prefill,
}: {
  onSubmit: (text: string) => void;
  phase?: InteractionPhase;
  prefill?: { requestId: number; text: string };
}): React.ReactElement {
  const [text, setText] = useState("");
  const [cursorPos, setCursorPos] = useState(0);
  const [history, setHistory] = useState<string[]>([]);
  const [historyIdx, setHistoryIdx] = useState(-1);
  const [draft, setDraft] = useState("");
  const [suggestionIdx, setSuggestionIdx] = useState(0);
  const textRef = useRef("");
  const cursorPosRef = useRef(0);
  const suggestions = getSlashCommandSuggestions(text);
  const selectedSuggestion = suggestions[Math.min(suggestionIdx, suggestions.length - 1)];

  // Refs to handle duplicate paste on Windows Terminal
  const justPastedRef = useRef(false);
  const pastedCharsRef = useRef<string[]>([]);
  const pastedIndexRef = useRef(0);
  const lastPasteTimeRef = useRef(0);

  const setCursor = (pos: number) => {
    cursorPosRef.current = pos;
    setCursorPos(pos);
  };

  useEffect(() => {
    if (!prefill) return;
    textRef.current = prefill.text;
    setText(prefill.text);
    cursorPosRef.current = prefill.text.length;
    setCursorPos(prefill.text.length);
    setSuggestionIdx(0);
  }, [prefill]);

  useInput((input, key) => {
    const acceptSuggestion = (suggestion: SlashCommandSuggestion) => {
      setHistoryIdx(-1);
      setDraft("");
      setSuggestionIdx(0);
      textRef.current = suggestion.insertText;
      setText(textRef.current);
      setCursor(textRef.current.length);
    };

    // Multi-line support: Alt+Enter (key.meta && key.return)
    if (key.return) {
      if (key.meta || key.ctrl) {
        setSuggestionIdx(0);
        const newText = insertAt(textRef.current, cursorPosRef.current, "\n");
        textRef.current = newText;
        setText(newText);
        setCursor(cursorPosRef.current + 1);
        return;
      }
      const currentText = textRef.current;
      const currentSuggestions = getSlashCommandSuggestions(currentText);
      const currentSuggestion =
        currentSuggestions[Math.min(suggestionIdx, currentSuggestions.length - 1)];
      if (currentSuggestion && shouldCompleteSuggestion(currentText, currentSuggestion)) {
        acceptSuggestion(currentSuggestion);
        return;
      }
      const t = currentText.trim();
      if (t) {
        setHistory((prev) => [...prev, currentText]);
        setHistoryIdx(-1);
        setDraft("");
        onSubmit(t);
      }
      setSuggestionIdx(0);
      textRef.current = "";
      setText("");
      setCursor(0);
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
        setDraft(textRef.current);
        nextIdx = history.length - 1;
      } else if (historyIdx > 0) {
        nextIdx = historyIdx - 1;
      } else {
        return; // already at oldest
      }
      setHistoryIdx(nextIdx);
      setSuggestionIdx(0);
      textRef.current = history[nextIdx] ?? "";
      setText(textRef.current);
      setCursor(textRef.current.length);
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
        textRef.current = draft;
        setText(textRef.current);
        setCursor(textRef.current.length);
      } else {
        setHistoryIdx(nextIdx);
        setSuggestionIdx(0);
        textRef.current = history[nextIdx] ?? "";
        setText(textRef.current);
        setCursor(textRef.current.length);
      }
      return;
    }

    if (key.leftArrow) {
      if (suggestions.length > 0) {
        setSuggestionIdx((idx) => (idx <= 0 ? suggestions.length - 1 : idx - 1));
        return;
      }
      setCursor(Math.max(0, cursorPosRef.current - 1));
      return;
    }

    if (key.rightArrow) {
      if (suggestions.length > 0) {
        setSuggestionIdx((idx) => (idx + 1) % suggestions.length);
        return;
      }
      setCursor(Math.min(textRef.current.length, cursorPosRef.current + 1));
      return;
    }

    if (key.ctrl && input === "a") {
      setCursor(0);
      return;
    }
    if (key.ctrl && input === "e") {
      setCursor(textRef.current.length);
      return;
    }

    if ((key.tab || input === "\t") && selectedSuggestion) {
      acceptSuggestion(selectedSuggestion);
      return;
    }

    if (key.backspace || key.delete) {
      setSuggestionIdx(0);
      if (cursorPosRef.current === 0) return;
      const pos = cursorPosRef.current;
      const newText = textRef.current.slice(0, pos - 1) + textRef.current.slice(pos);
      textRef.current = newText;
      setText(newText);
      setCursor(pos - 1);
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
        textRef.current = applyInlineEdits(textRef.current, normalized);
        setText(textRef.current);
        setCursor(textRef.current.length);
        return;
      }

      // Genuine paste chunk (multiple base characters or a newline).
      // Single typed graphemes fall through to the normal append path even if
      // they span multiple code points (combining diacritics).
      if (isPasteChunk(normalized)) {
        textRef.current += normalized;
        setText(textRef.current);
        setCursor(textRef.current.length);
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

      const newText = insertAt(textRef.current, cursorPosRef.current, normalized);
      textRef.current = newText;
      setText(newText);
      setCursor(cursorPosRef.current + normalized.length);
    }
  });

  return (
    <Box flexDirection="column" marginLeft={1} marginTop={1}>
      <Box>
        <Text color="cyan" bold>
          {"▶ "}
        </Text>
        <Text>{text.slice(0, cursorPos)}</Text>
        <Text color="cyan" bold>
          █
        </Text>
        <Text>{text.slice(cursorPos)}</Text>
      </Box>
      <Box marginTop={0}>
        <Text dimColor>
          {phase === "running" || phase === "cancelling"
            ? "(Processing… Ctrl+C to cancel)"
            : phase === "awaiting_input"
              ? "(Awaiting your response…)"
              : phase === "queue_paused"
                ? "(Queue paused — /queue resume to continue)"
                : "(Alt+Enter for newline, ←→ to move cursor, Up/Down for history)"}
        </Text>
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
