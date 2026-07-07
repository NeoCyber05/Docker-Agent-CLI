"""Startup plugin selector.

Shown before MCP servers are connected. The user picks which infrastructure
plugins (Docker, and future Kubernetes / cloud plugins) to connect for the
session. Multi-select is deliberate: the control plane aggregates tools from
every connected plugin, so several domains can run side by side.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Label, SelectionList
from textual.widgets.selection_list import Selection

from infra_agent.mcp.config import PluginDescriptor


class _ConfirmSelectionList(SelectionList[str]):
    """SelectionList where Enter confirms instead of toggling.

    ``space`` still toggles the highlighted plugin (inherited binding); Enter is
    remapped so the user can confirm the whole selection in one keystroke.
    """

    BINDINGS = [Binding("enter", "confirm", "Connect", show=False)]

    def action_confirm(self) -> None:
        # Defer to the app so confirm behaves the same from list or key binding.
        connect = getattr(self.app, "action_connect", None)
        if callable(connect):
            connect()


class PluginSelectionApp(App[list[str]]):
    """Multi-select plugin picker. ``run()`` returns the chosen names or ``None``."""

    CSS = """
    Screen {
        align: center middle;
    }

    #panel {
        width: 72;
        height: auto;
        max-height: 90%;
        border: round $accent;
        padding: 1 2;
    }

    #title {
        text-style: bold;
        color: $accent;
    }

    #hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    SelectionList {
        height: auto;
        max-height: 16;
    }
    """

    BINDINGS = [
        Binding("enter", "connect", "Connect"),
        Binding("a", "toggle_all", "Toggle all"),
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        plugins: list[PluginDescriptor],
        preselected: set[str],
    ) -> None:
        super().__init__()
        self._plugins = plugins
        self._preselected = preselected

    def compose(self) -> ComposeResult:
        with Vertical(id="panel"):
            yield Label("Select infrastructure plugins to connect", id="title")
            yield Label(
                "\u2191/\u2193 move \u00b7 space toggle \u00b7 a all \u00b7 enter connect \u00b7 q cancel",
                id="hint",
            )
            yield _ConfirmSelectionList(
                *[
                    Selection(
                        f"{plugin.label}  \u2014  {plugin.description}"
                        if plugin.description
                        else plugin.label,
                        plugin.name,
                        plugin.name in self._preselected,
                    )
                    for plugin in self._plugins
                ],
                id="plugins",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(SelectionList).focus()

    def action_connect(self) -> None:
        selection = self.query_one(SelectionList)
        self.exit([str(name) for name in selection.selected])

    def action_toggle_all(self) -> None:
        selection = self.query_one(SelectionList)
        all_names = {plugin.name for plugin in self._plugins}
        if set(selection.selected) == all_names:
            selection.deselect_all()
        else:
            selection.select_all()

    def action_cancel(self) -> None:
        self.exit(None)


def select_plugins(
    plugins: list[PluginDescriptor],
    preselected: list[str] | None = None,
) -> list[str] | None:
    """Prompt the user to choose plugins.

    Returns the selected plugin names, or ``None`` if the user cancelled. With no
    prior selection every plugin is pre-ticked so the common case is one keystroke.
    """
    if not plugins:
        return []
    available = {plugin.name for plugin in plugins}
    if preselected is None:
        pre = available
    else:
        pre = {name for name in preselected if name in available}
    return PluginSelectionApp(plugins, pre).run(inline=True)


__all__ = ["PluginSelectionApp", "select_plugins"]
