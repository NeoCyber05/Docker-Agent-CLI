"""Markdown and inline text formatting helpers for Rich/Textual rendering."""

from __future__ import annotations

import re
from io import StringIO

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_PATTERN = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_INLINE_CODE_PATTERN = re.compile(r"`([^`]+)`")
_HEADER_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$")
_HRULE_PATTERN = re.compile(r"^-{3,}$")
_TABLE_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")


def render_inline_markdown(
    text: str,
    *,
    base_style: str = "",
    emphasis_style: str = "bold cyan",
    italic_style: str = "italic",
    code_style: str = "cyan",
) -> Text:
    """Render basic inline markdown markers as styled Rich text.

    Supports ``**bold**``, ``*italic*``, and ``inline code``.
    """
    if not text:
        return Text("", style=base_style)

    segments: list[tuple[str, str]] = [(text, base_style)]
    for pattern, style in (
        (_BOLD_PATTERN, emphasis_style),
        (_ITALIC_PATTERN, italic_style),
        (_INLINE_CODE_PATTERN, code_style),
    ):
        updated: list[tuple[str, str]] = []
        for segment_text, segment_style in segments:
            if segment_style != base_style:
                updated.append((segment_text, segment_style))
                continue
            last_end = 0
            matched = False
            for match in pattern.finditer(segment_text):
                matched = True
                if match.start() > last_end:
                    updated.append((segment_text[last_end : match.start()], base_style))
                updated.append((match.group(1), style))
                last_end = match.end()
            if not matched:
                updated.append((segment_text, segment_style))
            elif last_end < len(segment_text):
                updated.append((segment_text[last_end:], base_style))
        segments = updated

    result = Text()
    for segment_text, segment_style in segments:
        if segment_text:
            result.append(segment_text, style=segment_style)
    return result


def _parse_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _looks_like_table_row(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped.startswith("|")
        and stripped.endswith("|")
        and "|" in stripped[1:-1]
    )


def _is_table_separator(line: str) -> bool:
    cells = _parse_table_row(line)
    if not cells:
        return False
    return all(_TABLE_SEPARATOR_CELL.fullmatch(cell) for cell in cells)


def _renderable_to_text(renderable: Table, *, width: int) -> Text:
    buffer = StringIO()
    console = Console(
        file=buffer,
        width=width,
        force_terminal=True,
        color_system="truecolor",
        legacy_windows=False,
        highlight=False,
    )
    console.print(renderable, end="")
    return Text.from_ansi(buffer.getvalue())


def _render_markdown_table(lines: list[str], *, width: int) -> Text:
    header_cells = _parse_table_row(lines[0])
    data_rows = [_parse_table_row(line) for line in lines[2:]]
    col_count = len(header_cells)

    table = Table(
        show_header=True,
        header_style="bold cyan",
        padding=(0, 1),
        expand=False,
        box=box.ROUNDED,
    )
    for header in header_cells:
        table.add_column(render_inline_markdown(header).plain, overflow="fold")

    for row in data_rows:
        cells = [
            render_inline_markdown(row[index]).plain if index < len(row) else ""
            for index in range(col_count)
        ]
        table.add_row(*cells)

    rendered = _renderable_to_text(table, width=width)
    if rendered.plain and not rendered.plain.endswith("\n"):
        rendered.append("\n")
    return rendered


def render_markdown(text: str, *, width: int = 100) -> Text:
    """Render assistant-facing markdown as styled Rich text.

    Supports inline emphasis, ATX headings, horizontal rules, and GFM pipe tables.
    """
    if not text:
        return Text("")

    lines = text.splitlines()
    result = Text()
    index = 0

    while index < len(lines):
        line = lines[index]

        if (
            _looks_like_table_row(line)
            and index + 1 < len(lines)
            and _is_table_separator(lines[index + 1])
        ):
            table_lines = [line, lines[index + 1]]
            index += 2
            while index < len(lines) and _looks_like_table_row(lines[index]):
                table_lines.append(lines[index])
                index += 1
            result.append_text(_render_markdown_table(table_lines, width=width))
            continue

        stripped = line.strip()
        if not stripped:
            if result.plain and not result.plain.endswith("\n\n"):
                result.append("\n")
            index += 1
            continue

        header_match = _HEADER_PATTERN.match(stripped)
        if header_match:
            level = len(header_match.group(1))
            emphasis = "bold cyan" if level <= 3 else "bold"
            result.append_text(
                render_inline_markdown(header_match.group(2), emphasis_style=emphasis)
            )
            result.append("\n")
            index += 1
            continue

        if _HRULE_PATTERN.match(stripped):
            result.append("─" * min(width, 48) + "\n", style="dim")
            index += 1
            continue

        if stripped.startswith("```"):
            fence = stripped
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            if code_lines:
                result.append("\n".join(code_lines) + "\n", style="dim cyan")
            elif fence != "```":
                result.append(fence + "\n", style="dim cyan")
            continue

        paragraph_lines = [line]
        index += 1
        while index < len(lines):
            next_line = lines[index]
            next_stripped = next_line.strip()
            if not next_stripped:
                break
            if (
                _looks_like_table_row(next_line)
                and index + 1 < len(lines)
                and _is_table_separator(lines[index + 1])
            ):
                break
            if _HEADER_PATTERN.match(next_stripped) or _HRULE_PATTERN.match(next_stripped):
                break
            if next_stripped.startswith("```"):
                break
            paragraph_lines.append(next_line)
            index += 1

        paragraph = "\n".join(paragraph_lines)
        result.append_text(render_inline_markdown(paragraph))
        result.append("\n")

    return result


__all__ = ["render_inline_markdown", "render_markdown"]
