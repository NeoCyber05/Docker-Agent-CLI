import { Box, Text } from "ink";
import type React from "react";
import { FormattedText } from "./FormattedText";

export interface UIMessage {
  key: number;
  role: "user" | "assistant" | "tool" | "error";
  text?: string;
  name?: string;
  status?: "running" | "done" | "error";
}

export function MessageList({ messages }: { messages: UIMessage[] }): React.ReactElement {
  return (
    <Box flexDirection="column">
      {messages.map((m) => {
        if (m.role === "user")
          return (
            <Box key={m.key}>
              <Text color="cyan">▶ </Text>
              <Text>{m.text}</Text>
            </Box>
          );
        if (m.role === "tool")
          return (
            <Box key={m.key}>
              <Text color="blue">[{m.name}]</Text>
              <Text dimColor> {m.text || m.status || ""}</Text>
            </Box>
          );
        if (m.role === "error")
          return (
            <Box key={m.key}>
              <Text color="red">error: {m.text}</Text>
            </Box>
          );
        return (
          <Box key={m.key}>
            <FormattedText text={m.text || ""} />
          </Box>
        );
      })}
    </Box>
  );
}
