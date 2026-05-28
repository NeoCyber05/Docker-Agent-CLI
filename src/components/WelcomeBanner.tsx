import * as os from "node:os";
import { Box, Text } from "ink";
import type React from "react";

const WHALE = [
  "        ##         .",
  "  ## ## ##        ==",
  "  ## ## ## ##    ===",
  '/""""""""""""""""\\___/ ===',
  "{                       /  ===-",
  "\\______ O           __/",
  " \\    \\         __/",
  "  \\____\\_______/",
];

interface Tip {
  cmd: string;
  desc: string;
}

const TIPS: Tip[] = [
  { cmd: "/help", desc: "Show all commands" },
  { cmd: "/stacks", desc: "List managed stacks" },
  { cmd: "/status <stack>", desc: "Inspect status & drift" },
  { cmd: "/quit", desc: "Exit the agent" },
];

export interface WelcomeBannerProps {
  version: string;
  username?: string;
  provider: string;
  compact?: boolean;
}

export function WelcomeBanner({
  version,
  username,
  provider,
  compact = false,
}: WelcomeBannerProps): React.ReactElement {
  const user = username ?? os.userInfo().username;
  if (compact) {
    return (
      <Box borderStyle="round" borderColor="cyan" paddingX={1}>
        <Text color="cyan" bold>
          docker agent{" "}
        </Text>
        <Text color="cyan">v{version}</Text>
        <Text dimColor> · provider: </Text>
        <Text color="yellow">{provider}</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1} paddingY={0}>
      <Box marginBottom={1}>
        <Text color="cyan" bold>
          docker agent{" "}
        </Text>
        <Text color="cyan">v{version}</Text>
        <Text dimColor> · provider: </Text>
        <Text color="yellow">{provider}</Text>
      </Box>

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
          {WHALE.map((line) => (
            <Box key={line}>
              <Text color="blue">{line}</Text>
            </Box>
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
