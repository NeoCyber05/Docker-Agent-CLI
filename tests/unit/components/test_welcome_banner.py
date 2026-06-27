from __future__ import annotations

from textual.app import App, ComposeResult

from io import StringIO

from rich.console import Console

from docker_agent.components.welcome_banner import WelcomeBanner, build_welcome_content


def _render_widget(widget: WelcomeBanner, *, width: int = 100) -> str:
    buffer = StringIO()
    Console(file=buffer, width=width).print(widget.content)
    return buffer.getvalue()


class WelcomeApp(App):
    def compose(self) -> ComposeResult:
        yield WelcomeBanner("0.1.0", username="tester")


async def test_welcome_banner_shows_version() -> None:
    app = WelcomeApp()
    async with app.run_test(size=(100, 30)) as pilot:
        banner = pilot.app.query_one(WelcomeBanner)
        rendered = _render_widget(banner)
        assert "Docker Agent CLI" in rendered
        assert "tester" in rendered


async def test_welcome_banner_compact_mode() -> None:
    content = build_welcome_content("1.2.3", username="alice", compact=True)
    text = str(content)
    assert "docker-agent" in text
    assert "v1.2.3" in text
    assert "Tips" not in text


def test_welcome_banner_shows_tips() -> None:
    from io import StringIO

    from rich.console import Console

    buffer = StringIO()
    Console(file=buffer, width=100).print(build_welcome_content("0.1.0", username="alice", compact=False))
    text = buffer.getvalue()
    assert "/help" in text
    assert "Tips for getting started" in text


async def test_welcome_banner_tips_render_on_right_column() -> None:
    from io import StringIO

    from rich.console import Console

    buffer = StringIO()
    Console(file=buffer, width=100).print(
        build_welcome_content("0.1.0", username="tester", compact=False)
    )
    rendered = buffer.getvalue()
    assert "Tips for getting started" in rendered
    assert "/help" in rendered
    assert "##" in rendered