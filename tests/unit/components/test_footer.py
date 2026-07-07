from __future__ import annotations

from textual.app import App, ComposeResult

from infra_agent.components.footer import StatusFooter, build_footer_content


class FooterApp(App):
    def compose(self) -> ComposeResult:
        yield StatusFooter(
            session_id="sess-1",
            usage={"input_tokens": 10, "output_tokens": 5},
            active_tool="list_stacks",
            queue_count=2,
        )


async def test_footer_shows_session_tokens_tool_queue() -> None:
    app = FooterApp()
    async with app.run_test() as pilot:
        footer = pilot.app.query_one(StatusFooter)
        rendered = str(footer.content)
        assert "session: sess-1" in rendered
        assert "tokens in/out: 10/5" in rendered
        assert "list_stacks" in rendered
        assert "queue: 2" in rendered


def test_footer_hides_zero_queue() -> None:
    content = build_footer_content(queue_count=0)
    assert "queue:" not in str(content)


def test_footer_shows_model_and_provider() -> None:
    content = build_footer_content(
        provider="openai",
        model="gpt-4o-mini",
        session_id="sess-1",
    )
    rendered = str(content)
    assert "gpt-4o-mini (openai)" in rendered


def test_footer_shows_provider_default_model_when_unset() -> None:
    content = build_footer_content(provider="ollama", model=None)
    assert "qwen2.5:14b (ollama)" in str(content)
