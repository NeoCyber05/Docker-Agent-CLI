from __future__ import annotations

from textual.app import App, ComposeResult

from src.components.welcome_banner import WelcomeBanner, build_welcome_content


class WelcomeApp(App):
    def compose(self) -> ComposeResult:
        yield WelcomeBanner("0.1.0", username="tester")


async def test_welcome_banner_shows_version() -> None:
    app = WelcomeApp()
    async with app.run_test() as pilot:
        banner = pilot.app.query_one(WelcomeBanner)
        assert "Docker Agent CLI" in str(banner.content)
        assert "tester" in str(banner.content)


async def test_welcome_banner_compact_mode() -> None:
    content = build_welcome_content("1.2.3", username="alice", compact=True)
    text = str(content)
    assert "docker-agent" in text
    assert "v1.2.3" in text
    assert "Tips" not in text


async def test_welcome_banner_shows_tips() -> None:
    content = build_welcome_content("0.1.0", username="alice", compact=False)
    text = str(content)
    assert "/help" in text
    assert "Tips for getting started" in text