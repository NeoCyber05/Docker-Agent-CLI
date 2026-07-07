"""Process-level CLI entrypoint.
"""

from __future__ import annotations

import io
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from textual.app import App

from infra_agent import __version__
from infra_agent.components.welcome_banner import (
    build_welcome_content,
    resolve_terminal_size,
    should_show_compact_banner,
)
from infra_agent.config import (
    load_user_config,
    project_state_dir,
    resolve_provider,
)
from infra_agent.query_engine import QueryEngine, restore_session_from_record
from infra_agent.screens.repl import REPL
from infra_agent.services.api import resolve_provider_for_request
from infra_agent.state.logger import StructuredLogger
from infra_agent.state.session_store import SessionRecord, SessionStore
from infra_agent.vault.api_key_store import create_api_key_store


@dataclass
class ParsedArgs:
    provider_flag: str | None = None
    model: str | None = None
    resume: bool | str | None = None
    yes: bool = False


cli = typer.Typer(
    name="infra-agent",
    help="Natural-language CLI for managing infrastructure via MCP plugins",
    add_completion=False,
)


_RESUME_LATEST = "__LATEST__"


def _parse_resume(value: str | None) -> bool | str | None:
    """Typer callback for ``--resume [id]``.

    - option omitted â†’ None
    - ``--resume`` alone â†’ True (via ``_RESUME_LATEST`` sentinel)
    - ``--resume <id>`` â†’ id string
    """
    if value is None:
        return None
    if value == _RESUME_LATEST:
        return True
    return value


def _normalize_resume_argv(argv: list[str]) -> list[str]:
    """Map bare ``--resume`` to a value Typer can parse."""
    normalized: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--resume":
            next_token = argv[index + 1] if index + 1 < len(argv) else None
            if next_token is None or next_token.startswith("-"):
                normalized.extend(["--resume", _RESUME_LATEST])
                index += 1
                continue
        normalized.append(token)
        index += 1
    return normalized


def _create_deps(args: ParsedArgs) -> dict[str, Any]:

    user_config = load_user_config()
    provider_name = resolve_provider(flag=args.provider_flag, config=user_config)
    model = args.model or user_config.model
    cwd = str(Path.cwd())
    api_key_store = create_api_key_store()
    provider = resolve_provider_for_request(provider_name, api_key_store=api_key_store)
    session_store = SessionStore(project_state_dir(cwd))
    deps: dict[str, Any] = {
        "cwd": cwd,
        "session_store": session_store,
        "provider": provider,
        "provider_name": provider_name,
        "api_key_store": api_key_store,
    }
    if model is not None:
        deps["model"] = model
    return deps


def render_welcome_banner_for_terminal(
    provider: str,
    version: str = __version__,
    columns: int | None = None,
    rows: int | None = None,
) -> str:
    """Render the welcome banner to a string before launching the TUI."""
    resolved_columns, resolved_rows = resolve_terminal_size(columns, rows)
    effective_columns = max(1, resolved_columns - 1)
    effective_rows = resolved_rows
    compact = should_show_compact_banner(resolved_columns, resolved_rows)
    content = build_welcome_content(version, compact=compact)
    buffer = io.StringIO()
    console = Console(file=buffer, width=effective_columns, height=effective_rows)
    console.print(content)
    output = buffer.getvalue()
    if not output.endswith("\n"):
        output += "\n"
    return output


def _resolve_resume(
    args: ParsedArgs,
    session_store: SessionStore,
) -> dict[str, SessionRecord] | None:
    if args.resume is None:
        return None
    if args.resume is True:
        record = session_store.latest()
        if record is None:
            sys.stderr.write("No previous session found to resume.\n")
            return None
    elif isinstance(args.resume, str):
        record = session_store.read(args.resume)
        if record is None:
            sys.stderr.write(f"Session {args.resume} not found.\n")
            return None
    else:
        return None
    sys.stderr.write(f"[infra-agent] Resuming session {record['id']}\n")
    return {"resumed_record": record}


def _run_chat_session(
    args: ParsedArgs,
    *,
    app_factory: Callable[..., App[Any]] | None = None,
) -> None:
    deps = _create_deps(args)
    session_store: SessionStore = deps["session_store"]
    resumed = _resolve_resume(args, session_store)

    engine = QueryEngine(
        cwd=deps["cwd"],
        provider=deps["provider"],
        model=deps.get("model"),
        session_store=session_store,
    )
    if resumed is not None:
        restore_session_from_record(
            engine=engine,
            record=resumed["resumed_record"],
            api_key_store=deps["api_key_store"],
        )

    log_dir = Path(deps["cwd"]) / ".docker-agent" / "logs"
    engine.set_logger(StructuredLogger(str(log_dir), engine.session_id))

    import asyncio

    from infra_agent.mcp.client import preload_mcp_runtime, warmup_mcp_stdio_transport

    _select_and_activate_plugins()

    console = Console(stderr=True)
    with console.status(
        "[bold cyan]Connecting selected plugins...[/bold cyan]", spinner="dots"
    ):
        warmup_mcp_stdio_transport()
        asyncio.run(preload_mcp_runtime(deps["cwd"]))

    factory = app_factory or REPL
    app = factory(
        engine=engine,
        version=__version__,
        api_key_store=deps["api_key_store"],
        show_banner=True,
        yes=args.yes,
        **(
            {"resumed_record": resumed["resumed_record"]}
            if resumed is not None
            else {}
        ),
    )
    app.run(inline=True)


def _select_and_activate_plugins() -> None:
    """Show the plugin selector and restrict the session to the chosen plugins.

    The previous selection (or all plugins on first run) is pre-ticked. Cancelling
    keeps the previous selection so launch never dead-ends on connecting nothing.
    """
    from infra_agent.mcp.client import set_active_plugin_selection
    from infra_agent.mcp.config import (
        list_available_plugins,
        load_plugin_selection,
        save_plugin_selection,
    )
    from infra_agent.screens.plugin_selection import select_plugins

    available = list_available_plugins()
    if not available:
        return

    previous = load_plugin_selection()
    chosen = select_plugins(available, previous)
    if chosen is None:
        chosen = previous if previous is not None else [plugin.name for plugin in available]
    else:
        save_plugin_selection(chosen)
    set_active_plugin_selection(chosen)


def run_chat_session(args: ParsedArgs) -> None:
    """Launch the interactive chat session."""
    _run_chat_session(args)


@cli.callback(invoke_without_command=True)
def _cli_callback(
    ctx: typer.Context,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="LLM provider: gemini, openai, ollama, openrouter"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="model id"),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("-y", "--yes", help="auto-approve non-destructive permissions"),
    ] = False,
    resume: Annotated[
        str | None,
        typer.Option(
            "--resume",
            help="resume a previous session (omit id for latest)",
            callback=_parse_resume,
        ),
    ] = None,
    version: Annotated[
        bool,
        typer.Option("--version", help="Show version", is_eager=True),
    ] = False,
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit(0)

    parsed = ParsedArgs(
        provider_flag=provider,
        model=model,
        resume=resume,
        yes=yes,
    )
    try:
        run_chat_session(parsed)
    except typer.Exit:
        raise
    except Exception as err:  # noqa: BLE001
        typer.echo(f"error: {err}", err=True)
        raise typer.Exit(1) from err


def main(argv: list[str] | None = None) -> None:
    """Console script entrypoint for ``infra-agent`` (alias: ``docker-agent``)."""
    extra = _normalize_resume_argv(argv if argv is not None else sys.argv[1:])
    cli(args=extra, standalone_mode=True)


__all__ = [
    "ParsedArgs",
    "cli",
    "main",
    "render_welcome_banner_for_terminal",
    "run_chat_session",
]
