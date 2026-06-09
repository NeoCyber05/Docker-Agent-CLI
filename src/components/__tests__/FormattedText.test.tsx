import { parseMarkdown } from "src/components/FormattedText";
import { describe, expect, test } from "vitest";

describe("parseMarkdown", () => {
  test("parses plain text without tables", () => {
    const text = "Hello world\nThis is normal text.";
    const blocks = parseMarkdown(text);
    expect(blocks).toEqual([{ type: "text", content: text }]);
  });

  test("parses markdown tables with text around them", () => {
    const text = `Here is a table:

| Stack Name | Services | Last Applied |
| :--- | :---: | ---: |
| nginx | 1 | 2026-05-29T23:00:32.645Z |
| redis | 2 | 2026-05-29T23:05:00.000Z |

Hope you like it!`;

    const blocks = parseMarkdown(text);

    expect(blocks).toHaveLength(3);
    expect(blocks[0]).toEqual({ type: "text", content: "Here is a table:\n" });
    expect(blocks[2]).toEqual({ type: "text", content: "\nHope you like it!" });

    expect(blocks[1]?.type).toBe("table");
    const table = (
      blocks[1] as { table: { headers: string[]; alignments: string[]; rows: string[][] } }
    ).table;
    expect(table.headers).toEqual(["Stack Name", "Services", "Last Applied"]);
    expect(table.alignments).toEqual(["left", "center", "right"]);
    expect(table.rows).toEqual([
      ["nginx", "1", "2026-05-29T23:00:32.645Z"],
      ["redis", "2", "2026-05-29T23:05:00.000Z"],
    ]);
  });

  test("handles tables without outer pipes", () => {
    const text = `Name | Value
---|---
foo | bar`;
    const blocks = parseMarkdown(text);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]?.type).toBe("table");
    const table = (
      blocks[0] as { table: { headers: string[]; alignments: string[]; rows: string[][] } }
    ).table;
    expect(table.headers).toEqual(["Name", "Value"]);
    expect(table.rows).toEqual([["foo", "bar"]]);
  });
});
