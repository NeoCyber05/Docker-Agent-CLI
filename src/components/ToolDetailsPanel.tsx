import { Box, Text } from "ink";
import type React from "react";
import type { ToolActivity } from "src/ui/activity";

export function ToolDetailsPanel({
  activity,
}: { activity: ToolActivity | null }): React.ReactElement {
  if (!activity) {
    return (
      <Box flexDirection="column" borderStyle="single" paddingX={1}>
        <Text dimColor>No tool selected.</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" borderStyle="single" paddingX={1}>
      <Text bold>{activity.title}</Text>
      <Text dimColor>{activity.summary}</Text>
      <Text dimColor>Status: {activity.status}</Text>
      {activity.progressMsgs.length > 0 && (
        <Box flexDirection="column" marginTop={1}>
          <Text underline>Progress</Text>
          {activity.progressMsgs.map((msg, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: stable order
            <Text key={i} dimColor wrap="wrap">
              {msg}
            </Text>
          ))}
        </Box>
      )}
      {activity.detailLines.length > 0 && (
        <Box flexDirection="column" marginTop={1}>
          <Text underline>Details</Text>
          {activity.detailLines.map((line, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: stable order
            <Text key={i} wrap="wrap">
              {line}
            </Text>
          ))}
        </Box>
      )}
    </Box>
  );
}
