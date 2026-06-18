import { Box, Text, useInput } from "ink";
import type React from "react";
import { useEffect, useMemo, useState } from "react";
import type { ProviderName } from "src/config";
import { type CatalogRow, filterRows, providerLabel } from "src/services/modelCatalog";

const PAGE_SIZE = 10;

function selectableRows(rows: CatalogRow[]): CatalogRow[] {
  return rows.filter((r) => r.kind === "model" || r.kind === "connect");
}

export function ModelPickerDialog({
  rows,
  current,
  onSelect,
  onConnectProvider,
  onCancel,
}: {
  rows: CatalogRow[];
  current?: { provider: ProviderName; model: string };
  onSelect: (choice: { provider: ProviderName; model: string }) => void;
  onConnectProvider: (provider?: ProviderName) => void;
  onCancel: () => void;
}): React.ReactElement {
  const [query, setQuery] = useState("");
  const filteredRows = useMemo(() => filterRows(rows, query), [rows, query]);
  const selectable = useMemo(() => selectableRows(filteredRows), [filteredRows]);

  const initialIndex = useMemo(() => {
    if (!current) return 0;
    const idx = selectable.findIndex(
      (r) => r.kind === "model" && r.provider === current.provider && r.model === current.model,
    );
    return Math.max(0, idx);
  }, [selectable, current]);

  const [index, setIndex] = useState(initialIndex);

  useEffect(() => {
    setIndex((i) => Math.min(i, Math.max(0, selectable.length - 1)));
  }, [selectable.length]);

  useInput((char, key) => {
    if (key.upArrow) {
      if (selectable.length > 0) {
        setIndex((i) => (i - 1 + selectable.length) % selectable.length);
      }
    } else if (key.downArrow) {
      if (selectable.length > 0) {
        setIndex((i) => (i + 1) % selectable.length);
      }
    } else if (key.return) {
      const choice = selectable[index];
      if (!choice) return;
      if (choice.kind === "model") {
        onSelect({ provider: choice.provider, model: choice.model });
      } else {
        onConnectProvider(choice.provider);
      }
    } else if (key.tab) {
      onConnectProvider();
    } else if (key.escape) {
      onCancel();
    } else if (key.backspace || key.delete) {
      setQuery((q) => q.slice(0, -1));
      setIndex(0);
    } else if (char && !key.ctrl && !key.meta) {
      setQuery((q) => q + char);
      setIndex(0);
    }
  });

  const selectedRow = selectable[index];
  const selectedDisplayIndex = selectedRow !== undefined ? filteredRows.indexOf(selectedRow) : 0;
  const start = Math.min(
    Math.max(0, selectedDisplayIndex - Math.floor(PAGE_SIZE / 2)),
    Math.max(0, filteredRows.length - PAGE_SIZE),
  );
  const visible = filteredRows.slice(start, start + PAGE_SIZE);

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="cyan"
      paddingX={1}
      marginY={1}
      overflowX="hidden"
    >
      <Text bold color="cyan">
        Select model
      </Text>
      <Text dimColor>{query.length > 0 ? query : "[type to filter]"}</Text>
      <Box marginTop={1} flexDirection="column">
        {start > 0 && <Text dimColor> ↑ more…</Text>}
        {visible.map((row) => {
          if (row.kind === "header") {
            return (
              <Text key={`header-${row.provider}`} bold>
                {providerLabel(row.provider)}
                {row.connected ? <Text color="green"> ✓</Text> : null}
              </Text>
            );
          }

          const selected = row === selectedRow;
          const highlight = selected
            ? { color: "black" as const, backgroundColor: "cyan" as const }
            : {};

          if (row.kind === "connect") {
            return (
              <Text key={`connect-${row.provider}`} {...highlight}>
                {selected ? "❯ " : "  "}
                Not connected
              </Text>
            );
          }

          const isCurrent = current?.provider === row.provider && current?.model === row.model;
          return (
            <Text key={`model-${row.provider}-${row.model}`} {...highlight}>
              {selected ? "❯ " : "  "}
              {row.model}
              {isCurrent ? " (current)" : ""}
            </Text>
          );
        })}
        {start + PAGE_SIZE < filteredRows.length && <Text dimColor> ↓ more…</Text>}
      </Box>
      <Box marginTop={1}>
        <Text bold>
          [↑/↓] navigate [type] filter [Enter] select [Tab] Connect provider [Esc] cancel
        </Text>
      </Box>
    </Box>
  );
}
