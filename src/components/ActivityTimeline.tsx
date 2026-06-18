import { Box, Static, Text } from "ink";
import type React from "react";
import type { ActivityItem, ToolActivity } from "src/ui/activity";
import { FormattedText } from "./FormattedText";

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function statusSymbol(status: ToolActivity["status"]): string {
  switch (status) {
    case "running":
      return "●";
    case "completed":
      return "✓";
    case "failed":
      return "!";
    case "cancelled":
      return "×";
  }
}

function statusText(status: ToolActivity["status"]): string {
  switch (status) {
    case "running":
      return "running";
    case "completed":
      return "completed";
    case "failed":
      return "failed";
    case "cancelled":
      return "cancelled";
  }
}

function ToolActivityRow({ activity, isActive }: { activity: ToolActivity; isActive?: boolean }) {
  const duration =
    activity.endTime !== undefined
      ? formatDuration(activity.endTime - activity.startTime)
      : isActive
        ? formatDuration(Date.now() - activity.startTime)
        : "";
  const recentProgress = activity.progressMsgs.slice(-3);

  return (
    <Box flexDirection="column">
      <Box flexDirection="row" gap={1}>
        {isActive ? (
          <Text color="yellow">{statusSymbol(activity.status)}</Text>
        ) : (
          <Text>{statusSymbol(activity.status)}</Text>
        )}
        <Text bold>{activity.title}</Text>
        <Text dimColor>({activity.summary})</Text>
        <Text dimColor>[{statusText(activity.status)}]</Text>
        {duration ? <Text dimColor>{duration}</Text> : null}
      </Box>
      {recentProgress.length > 0 && (
        <Box flexDirection="column" paddingLeft={2}>
          {recentProgress.map((msg, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: stable order for progress lines
            <Text key={i} dimColor wrap="wrap">
              {msg}
            </Text>
          ))}
        </Box>
      )}
    </Box>
  );
}

function ActivityRow({ item }: { item: ActivityItem }) {
  if (item.type === "text") {
    if (item.role === "user") {
      return (
        <Box flexDirection="row">
          <Text color="cyan">▶ </Text>
          <Text>{item.text}</Text>
        </Box>
      );
    }
    if (item.role === "error") {
      return (
        <Box flexDirection="row">
          <Text color="red">error: {item.text}</Text>
        </Box>
      );
    }
    return (
      <Box flexDirection="column">
        <Text color="magenta" bold>
          Agent
        </Text>
        <FormattedText text={item.text} />
      </Box>
    );
  }
  if (item.type === "tool") {
    return <ToolActivityRow activity={item} />;
  }
  if (item.type === "usage") {
    return (
      <Box flexDirection="row">
        <Text dimColor>
          usage: {item.inputTokens} in / {item.outputTokens} out
        </Text>
      </Box>
    );
  }
  if (item.type === "rollback") {
    return (
      <Box flexDirection="row">
        <Text color={item.ok === false ? "red" : "yellow"}>
          rollback {item.phase} for {item.stackName}
          {item.ok !== undefined ? ` — ${item.ok ? "ok" : "FAILED"}` : ""}
        </Text>
      </Box>
    );
  }
  return null;
}

export function ActivityTimeline({
  items,
  activeToolActivityId,
}: {
  items: ActivityItem[];
  activeToolActivityId: string | null;
}): React.ReactElement {
  const activeItem = items.find((i) => i.type === "tool" && i.id === activeToolActivityId) as
    | ToolActivity
    | undefined;
  const lastItem = items[items.length - 1];
  const activeText =
    lastItem?.type === "text" && lastItem.role === "assistant" ? lastItem : undefined;
  const committedItems = items.filter(
    (item) =>
      !(item.type === "tool" && item.id === activeToolActivityId) && item.id !== activeText?.id,
  );

  return (
    <Box flexDirection="column">
      <Static items={committedItems}>{(item) => <ActivityRow key={item.id} item={item} />}</Static>
      {activeItem && (
        <Box flexDirection="column" marginTop={committedItems.length > 0 ? 1 : 0}>
          <ToolActivityRow activity={activeItem} isActive />
        </Box>
      )}
      {activeText && <ActivityRow item={activeText} />}
    </Box>
  );
}
