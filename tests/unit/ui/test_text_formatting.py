from __future__ import annotations

from docker_agent.ui.text_formatting import render_inline_markdown


def test_render_inline_markdown_strips_bold_markers() -> None:
    rendered = render_inline_markdown("Deploy **PostgreSQL** with Redis")
    assert rendered.plain == "Deploy PostgreSQL with Redis"
    assert "**" not in rendered.plain
    assert any("bold" in (span.style or "") for span in rendered.spans)


def test_render_inline_markdown_handles_multiple_emphasis() -> None:
    rendered = render_inline_markdown("**A** and **B**")
    assert rendered.plain == "A and B"
    bold_spans = [span for span in rendered.spans if span.style and "bold" in span.style]
    assert len(bold_spans) == 2


def test_render_inline_markdown_handles_italic_and_code() -> None:
    rendered = render_inline_markdown("Use *italic* and `code`")
    assert rendered.plain == "Use italic and code"
    assert any("italic" in (span.style or "") for span in rendered.spans)
    assert any("cyan" in (span.style or "") for span in rendered.spans)


def test_render_inline_markdown_leaves_unclosed_markers() -> None:
    rendered = render_inline_markdown("broken **bold")
    assert rendered.plain == "broken **bold"
