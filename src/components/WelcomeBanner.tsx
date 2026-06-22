import * as os from "node:os";
import { Box, Text } from "ink";
import type React from "react";

const WHALE = [
  "          ##         .",
  "    ## ## ##        ==",
  " ## ## ## ##       ===",
  '/"""""""""""""""\\___/ ===',
  "{                   /  ===-",
  "\\______ o         __/",
  " \\    \\         __/",
  "  \\____\\_______/",
];

type SegType = "container" | "water" | "eye" | "outline";

function segColor(type: SegType): string {
  switch (type) {
    case "container":
      return "blue";
    case "water":
      return "cyan";
    case "eye":
      return "green";
    default:
      return "cyan";
  }
}

function charType(ch: string): SegType {
  if (ch === "#") return "container";
  if (ch === "o" || ch === "●") return "eye";
  if (ch === "=" || ch === "." || ch === "~") return "water";
  return "outline";
}

function WhaleLine({ line }: { line: string }): React.ReactElement {
  const segs: { text: string; type: SegType }[] = [];
  let buf = "";
  let cur: SegType = "outline";
  for (const ch of line) {
    const t = charType(ch);
    if (t !== cur) {
      if (buf) segs.push({ text: buf, type: cur });
      buf = ch;
      cur = t;
    } else {
      buf += ch;
    }
  }
  if (buf) segs.push({ text: buf, type: cur });
  return (
    <Box>
      {segs.map((s, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: segments derived from static line string
        <Text key={i} color={segColor(s.type)}>
          {s.text}
        </Text>
      ))}
    </Box>
  );
}

interface Tip {
  cmd: string;
  desc: string;
}

const TIPS: Tip[] = [
  { cmd: "/help", desc: "Show all commands & shortcuts" },
  { cmd: "/model", desc: "Browse or set the active model" },
  { cmd: "/connect", desc: "Connect gemini, openai, or ollama" },
  { cmd: "/stacks", desc: "List managed stacks" },
  { cmd: "Ctrl+O", desc: "Open tool details panel" },
  { cmd: "/exit", desc: "Exit the agent" },
];

export interface WelcomeBannerProps {
  version: string;
  username?: string;
  provider: string;
  model?: string;
  compact?: boolean;
}

export function WelcomeBanner({
  version,
  username,
  compact = false,
}: WelcomeBannerProps): React.ReactElement {
  const user = username ?? os.userInfo().username;

  if (compact) {
    return (
      <Box borderStyle="round" borderColor="cyan" paddingX={1} overflowX="hidden">
        <Text color="cyan" bold>
          docker-agent{" "}
        </Text>
        <Text color="cyan">v{version}</Text>
      </Box>
    );
  }

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="cyan"
      paddingX={1}
      paddingY={0}
      overflowX="hidden"
    >
      <Box flexDirection="row">
        <Box flexDirection="column" width={38} paddingRight={2}>
          <Box justifyContent="center" marginBottom={1}>
            <Text>
              Welcome back,{" "}
              <Text color="cyan" bold>
                {user}
              </Text>
              !
            </Text>
          </Box>
          {WHALE.map((line, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: WHALE is static
            <WhaleLine key={i} line={line} />
          ))}
          <Box justifyContent="center" marginTop={1}>
            <Text color="cyan" bold>
              Docker Agent CLI
            </Text>
          </Box>
          <Box justifyContent="center">
            <Text dimColor>Your AI teammate for containerized workflows</Text>
          </Box>
        </Box>

        <Box flexDirection="column" flexGrow={1}>
          <Text color="cyan" bold>
            Tips for getting started
          </Text>
          <Box marginTop={1} flexDirection="column">
            {TIPS.map((t) => (
              <Box key={t.cmd}>
                <Text color="cyan">{"> "}</Text>
                <Box width={20}>
                  <Text color="cyan">{t.cmd}</Text>
                </Box>
                <Text>{t.desc}</Text>
              </Box>
            ))}
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
