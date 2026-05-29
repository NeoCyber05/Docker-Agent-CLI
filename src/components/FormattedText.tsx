import { Box, Text } from "ink";
import React from "react";

interface ParsedTable {
  headers: string[];
  alignments: ("left" | "center" | "right")[];
  rows: string[][];
}

type Block = { type: "text"; content: string } | { type: "table"; table: ParsedTable };

function parseTableRow(line: string): string[] {
  const trimmed = line.trim();
  const parts = trimmed.split("|");
  if (parts[0] === "") {
    parts.shift();
  }
  if (parts[parts.length - 1] === "") {
    parts.pop();
  }
  return parts.map((p) => p.trim());
}

function isDividerLine(line: string): boolean {
  const trimmed = line.trim();
  return /^[|:\-\s]+$/.test(trimmed) && trimmed.includes("-") && trimmed.includes("|");
}

function parseAlignments(dividerLine: string, colCount: number): ("left" | "center" | "right")[] {
  const parts = parseTableRow(dividerLine);
  const alignments: ("left" | "center" | "right")[] = [];

  for (let i = 0; i < colCount; i++) {
    const part = parts[i] || "";
    const left = part.startsWith(":");
    const right = part.endsWith(":");
    if (left && right) {
      alignments.push("center");
    } else if (right) {
      alignments.push("right");
    } else {
      alignments.push("left");
    }
  }

  return alignments;
}

export function parseMarkdown(text: string): Block[] {
  const lines = text.split("\n");
  const blocks: Block[] = [];
  let currentTextLines: string[] = [];

  const flushText = () => {
    if (currentTextLines.length > 0) {
      blocks.push({ type: "text", content: currentTextLines.join("\n") });
      currentTextLines = [];
    }
  };

  let i = 0;
  while (i < lines.length) {
    const line = lines[i]!;

    if (line.includes("|") && i + 1 < lines.length && isDividerLine(lines[i + 1]!)) {
      flushText();

      const headerLine = line;
      const dividerLine = lines[i + 1]!;
      i += 2;

      const headers = parseTableRow(headerLine);
      const alignments = parseAlignments(dividerLine, headers.length);
      const rows: string[][] = [];

      while (i < lines.length && lines[i]!.includes("|") && !isDividerLine(lines[i]!)) {
        rows.push(parseTableRow(lines[i]!));
        i++;
      }

      blocks.push({
        type: "table",
        table: { headers, alignments, rows },
      });
      continue;
    }

    currentTextLines.push(line);
    i++;
  }

  flushText();
  return blocks;
}

function padString(str: string, width: number, align: "left" | "center" | "right"): string {
  if (str.length >= width) return str;
  const extra = width - str.length;
  if (align === "left") {
    return str + " ".repeat(extra);
  }
  if (align === "right") {
    return " ".repeat(extra) + str;
  }
  const leftPad = Math.floor(extra / 2);
  const rightPad = extra - leftPad;
  return " ".repeat(leftPad) + str + " ".repeat(rightPad);
}

export function FormattedTable({ table }: { table: ParsedTable }): React.ReactElement {
  const { headers, alignments, rows } = table;

  // Calculate the maximum width of each column
  const colWidths = headers.map((h, colIndex) => {
    let max = h.length;
    for (const row of rows) {
      const val = row[colIndex] || "";
      if (val.length > max) {
        max = val.length;
      }
    }
    return max;
  });

  // Top border: ┌───┬───┐
  const topBorder = `┌${colWidths.map((w) => "─".repeat(w + 2)).join("┬")}┐`;

  // Header row: │ col1 │ col2 │
  const headerRow = (
    <Box flexDirection="row">
      <Text dimColor>│</Text>
      {headers.map((h, i) => {
        const width = colWidths[i]!;
        const align = alignments[i] || "left";
        return (
          <React.Fragment key={i}>
            <Text bold color="cyan">
              {` ${padString(h, width, align)} `}
            </Text>
            <Text dimColor>│</Text>
          </React.Fragment>
        );
      })}
    </Box>
  );

  // Separator line: ├───┼───┤
  const sepLine = `├${colWidths.map((w) => "─".repeat(w + 2)).join("┼")}┤`;

  // Data rows
  const renderedRows = rows.map((row, rowIdx) => (
    // biome-ignore lint/correctness/useJsxKeyInIterable: unique indices/values
    <Box flexDirection="row" key={rowIdx}>
      <Text dimColor>│</Text>
      {colWidths.map((w, colIdx) => {
        const val = row[colIdx] || "";
        const align = alignments[colIdx] || "left";
        return (
          // biome-ignore lint/correctness/useJsxKeyInIterable: stable index key
          <React.Fragment key={colIdx}>
            <Text>{` ${padString(val, w, align)} `}</Text>
            <Text dimColor>│</Text>
          </React.Fragment>
        );
      })}
    </Box>
  ));

  // Bottom border: └───┴───┘
  const bottomBorder = `└${colWidths.map((w) => "─".repeat(w + 2)).join("┴")}┘`;

  return (
    <Box flexDirection="column" marginY={1}>
      <Text dimColor>{topBorder}</Text>
      {headerRow}
      <Text dimColor>{sepLine}</Text>
      {renderedRows}
      <Text dimColor>{bottomBorder}</Text>
    </Box>
  );
}

export function FormattedText({ text }: { text: string }): React.ReactElement {
  const blocks = React.useMemo(() => parseMarkdown(text), [text]);

  return (
    <Box flexDirection="column">
      {blocks.map((block, idx) => {
        if (block.type === "table") {
          // biome-ignore lint/correctness/useJsxKeyInIterable: stable block index
          return <FormattedTable key={idx} table={block.table} />;
        }
        return (
          // biome-ignore lint/correctness/useJsxKeyInIterable: stable block index
          <Box key={idx}>
            <Text>{block.content}</Text>
          </Box>
        );
      })}
    </Box>
  );
}
