"""Main REPL screen.

Parity: ``src/screens/REPL.tsx``.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, cast

from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widgets import Input, Static


from docker_agent.commands.registry import Command, create_default_registry
from docker_agent.components.activity_timeline import ActivityTimeline
from docker_agent.components.api_key_input_dialog import ApiKeyInputDialog
from docker_agent.components.command_palette import CommandPalette
from docker_agent.components.footer import StatusFooter, build_footer_content
from docker_agent.components.log_pane import LogPane
from docker_agent.components.model_picker_dialog import (
    ModelChoice,
    ModelPickerClosed,
    ModelPickerDialog,
)
from docker_agent.components.ollama_setup_dialog import OllamaSetupDialog
from docker_agent.components.permission_dialog import PermissionAnswered, PermissionDialog
from docker_agent.components.prompt_input import PromptInput, PromptSubmitted, ResumeQueue
from docker_agent.components.provider_connect_dialog import ProviderConnectDialog
from docker_agent.components.queue_panel import QueuePanel
from docker_agent.components.secrets_input_dialog import SecretsInputDialog
from docker_agent.components.thinking_indicator import ThinkingIndicator
from docker_agent.components.tool_details_panel import ToolDetailsPanel
from docker_agent.components.typed_confirm_dialog import (
    InlineConfirmAnswered,
    InlineConfirmDialog,
    TypedConfirmDialog,
)
from docker_agent.components.welcome_banner import (
    COMPACT_WELCOME_MAX_ROWS,
    WelcomeBanner,
    resolve_terminal_size,
)
from docker_agent.config import PROVIDER_NAMES, ProviderName, stack_state_yaml_path
from docker_agent.query_engine import QueryEngine
from docker_agent.screens.apply_slash_effects import SlashEffectApplierDeps, apply_slash_effects
from docker_agent.screens.use_interaction_session import InteractionSession
from docker_agent.services.api import resolve_provider_for_request
from docker_agent.services.model_catalog import build_model_catalog, flatten_catalog
from docker_agent.services.provider_status import get_provider_statuses
from docker_agent.slash_router import SlashRouterContext, route_slash_command
from docker_agent.state.logger import StructuredLogger
from docker_agent.state.secret_redactor import scrub_line
from docker_agent.tools.shared.secret_keys import SecretKeysContext, collect_secret_keys
from docker_agent.types.events import (
    PermissionRequest,
    PlanReady,
    SecretsInputRequest,
    TypedConfirmRequest,
)
from docker_agent.types.permissions import Approve, Deny, PermissionResponse
from docker_agent.ui.activity import ToolActivity
from docker_agent.vault.api_key_store import (
    ApiKeyProviderName,
    ApiKeyStore,
    api_key_env_var,
    create_api_key_store,
    describe_api_key_status,
    is_api_key_provider_name,
)


class REPL(App[None]):
    DEFAULT_CSS = """
    REPL Screen {
        layout: vertical;
    }

    #welcome {
        height: auto;
        max-height: 15;
    }

    #header {
        height: auto;
        max-height: 3;
    }

    #timeline {
        height: 1fr;
        min-height: 4;
    }

    #timeline-content {
        height: auto;
    }

    #prompt {
        height: auto;
        max-height: 8;
    }

    #permission-prompt {
        height: auto;
        max-height: 12;
    }

    #inline-confirm {
        height: auto;
        max-height: 8;
    }

    #footer {
        height: auto;
        max-height: 3;
    }
    """

    BINDINGS = [
        ("ctrl+c", "cancel", "Cancel"),
        ("ctrl+o", "toggle_details", "Details"),
        ("ctrl+p", "toggle_palette", "Palette"),
        ("ctrl+q", "toggle_queue", "Queue"),
    ]

    show_banner: reactive[bool] = reactive(True)
    active_provider_name: reactive[str] = reactive("openai")
    active_model: reactive[str | None] = reactive(None)
    show_details: reactive[bool] = reactive(False)
    show_palette: reactive[bool] = reactive(False)
    show_queue: reactive[bool] = reactive(False)

    def __init__(
        self,
        *,
        engine: QueryEngine,
        version: str,
        api_key_store: ApiKeyStore | None = None,
        show_banner: bool = True,
        yes: bool = False,
        resumed_record: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.engine = engine
        self.version = version
        self.api_key_store = api_key_store or create_api_key_store()
        self.show_banner = show_banner
        self.yes = yes
        self.resumed_record = resumed_record
        self.session = InteractionSession(engine)
        self._session_task: asyncio.Task[None] | None = None
        self._tick_task: asyncio.Task[None] | None = None
        self._log_controller: asyncio.Event | None = None
        self._log_lines: list[str] = []
        self._active_log_pane: LogPane | None = None
        self._local_pending: str | None = None
        self._model_picker_waiter: asyncio.Future[ModelChoice | str | None] | None = None
        self._timeline_key = 0
        self._timeline_signature: tuple[Any, ...] | None = None
        self._cwd = engine._cwd  # noqa: SLF001
        self._state_store = engine._state_store  # noqa: SLF001
        self._compose_runner = engine._compose_runner  # noqa: SLF001
        self._session_store = engine._session_store  # noqa: SLF001
        self.active_provider_name = getattr(engine.provider, "name", "unknown")
        self.active_model = engine.model

    def on_mount(self) -> None:
        log_dir = Path(self._cwd) / ".docker-agent" / "logs"
        self.engine.set_logger(StructuredLogger(str(log_dir), self.engine.session_id))
        self._session_task = asyncio.create_task(self.session.run_loop())
        if self.resumed_record:
            from docker_agent.state.session_store import session_cwd_mismatch_warning

            warning = session_cwd_mismatch_warning(self.resumed_record, self._cwd)
            if warning:
                self.session.dispatch_activity({"type": "assistant_text", "delta": warning})
        self._tick_task = asyncio.create_task(self._tick_ui_loop())

    def on_unmount(self) -> None:
        if self._session_task is not None:
            self._session_task.cancel()
        if self._tick_task is not None:
            self._tick_task.cancel()
            self._tick_task = None
        self._stop_log_pane()

    def compose(self) -> ComposeResult:
        if self.show_banner:
            _, term_rows = resolve_terminal_size()
            yield WelcomeBanner(
                version=self.version,
                provider=self.active_provider_name,
                model=self.active_model,
                compact=term_rows <= COMPACT_WELCOME_MAX_ROWS,
                id="welcome",
            )
        else:
            yield Static(
                (
                    f"docker-agent | provider: {self.active_provider_name} | "
                    f"model: {self.active_model or 'default'}"
                ),
                id="header",
            )
        with VerticalScroll(id="timeline"):
            yield ActivityTimeline(
                items=self.session.activity_state.items,
                active_tool_activity_id=self.session.activity_state.active_tool_activity_id,
                id="timeline-content",
            )
        yield PromptInput(id="prompt")
        if self.session.interaction.phase == "running":
            yield ThinkingIndicator(id="thinking")
        yield StatusFooter(
            usage=self.engine.total_usage,
            session_id=self.engine.session_id,
            active_tool=self._active_tool_title(),
            queue_count=len(self.session.interaction.queue),
            provider=self.active_provider_name,
            model=self.active_model,
            id="footer",
        )

    def _active_tool_title(self) -> str | None:
        active_id = self.session.activity_state.active_tool_activity_id
        for item in self.session.activity_state.items:
            if item.type == "tool" and item.id == active_id:
                return item.title
        return None

    def _latest_tool(self) -> ToolActivity | None:
        for item in reversed(self.session.activity_state.items):
            if item.type == "tool":
                return item
        return None

    def _timeline_signature_value(self) -> tuple[Any, ...]:
        items = self.session.activity_state.items
        active = self.session.activity_state.active_tool_activity_id
        if not items:
            return (0, active)
        last = items[-1]
        if last.type == "tool":
            tail = (last.status, tuple(last.progress_msgs[-3:]), last.title)
        elif last.type == "text":
            tail = (last.role, last.text[-120:])
        elif last.type == "plan":
            tail = (last.status, last.show_yaml, last.show_config, last.request_id)
        else:
            tail = (last.type,)
        return (len(items), active, tail)

    def _refresh_ui(self) -> None:
        try:
            self.engine.set_activity_snapshot(self.session.activity_state.items)
            timeline = self.query_one("#timeline-content", ActivityTimeline)
            timeline.items = self.session.activity_state.items
            timeline.active_tool_activity_id = self.session.activity_state.active_tool_activity_id
            timeline.refresh_timeline()
            signature = self._timeline_signature_value()
            if signature != self._timeline_signature:
                self.query_one("#timeline", VerticalScroll).scroll_end(animate=False)
                self._timeline_signature = signature
            prompt = self.query_one("#prompt", PromptInput)
            prompt.phase = self.session.interaction.phase
            prompt_input = self._prompt_input()
            if prompt_input is not None:
                prompt_input.disabled = self._input_blocked()
            footer = self.query_one("#footer", StatusFooter)
            footer.update(
                build_footer_content(
                    usage=self.engine.total_usage,
                    session_id=self.engine.session_id,
                    active_tool=self._active_tool_title(),
                    queue_count=len(self.session.interaction.queue),
                    provider=self.active_provider_name,
                    model=self.active_model,
                )
            )
            if self._model_picker_waiter is not None:
                try:
                    picker = self.query_one("#model-picker", ModelPickerDialog)
                    if self.focused is not picker:
                        self.set_focus(picker)
                except Exception:
                    pass
            thinking = self.query("#thinking")
            show_thinking = (
                self.session.interaction.phase in {"running", "cancelling"}
                and self.session.pending_event is None
                and self._local_pending is None
            )
            if show_thinking and not thinking:
                self.mount(ThinkingIndicator(id="thinking"), after="#timeline")
            elif not show_thinking and thinking:
                thinking.remove()
            elif show_thinking and thinking:
                active_title = self._active_tool_title()
                indicator = self.query_one("#thinking", ThinkingIndicator)
                indicator.label = active_title if active_title else "Thinking"
        except Exception as err:
            import traceback
            with open("ui_error.log", "a", encoding="utf-8") as f:
                f.write(f"UI Refresh Error: {err}\n")
                traceback.print_exc(file=f)
            return

    async def _tick_ui_loop(self) -> None:
        while True:
            await asyncio.sleep(0.05)
            try:
                self._refresh_ui()
                if self.yes and isinstance(self.session.pending_event, PermissionRequest):
                    self.session.respond(self.session.pending_event.id, Approve())
                if self.yes and isinstance(self.session.pending_event, PlanReady):
                    self._respond_to_plan(Approve())
                self._schedule_pending_dialog()
            except asyncio.CancelledError:
                raise
            except Exception as err:
                import traceback
                with open("ui_error.log", "a", encoding="utf-8") as f:
                    f.write(f"UI Tick Loop Error: {err}\n")
                    traceback.print_exc(file=f)

    def _schedule_pending_dialog(self) -> None:
        if self.session.pending_event is None or self._local_pending is not None:
            return
        self._show_pending_dialog()

    def _show_pending_dialog(self) -> None:
        if self.session.pending_event is None or self._local_pending is not None:
            return
        pending = self.session.pending_event

        if isinstance(pending, PermissionRequest):
            self._local_pending = "permission"
            self._lock_prompt_input()
            if not self.query("#permission-prompt"):
                self.mount(
                    PermissionDialog(
                        tool=pending.tool,
                        input_data=pending.input,
                        id="permission-prompt",
                    ),
                    after="#timeline",
                )
                self.set_focus(self.query_one("#permission-prompt", PermissionDialog))
            return

        if isinstance(pending, PlanReady):
            self._local_pending = "plan"
            self._lock_prompt_input()
            return

        self._local_pending = "dialog"
        self._lock_prompt_input()

        def finish(result: Any) -> None:
            if result is not None:
                self.session.respond(pending.id, result)
            self._local_pending = None
            self._unlock_prompt_input()

        if isinstance(pending, TypedConfirmRequest):
            self._local_pending = "confirm"
            self._lock_prompt_input()
            if not self.query("#inline-confirm"):
                self.mount(
                    InlineConfirmDialog(
                        phrase=pending.phrase,
                        reason=pending.reason,
                        id="inline-confirm",
                    ),
                    after="#timeline",
                )
                self.set_focus(self.query_one("#inline-confirm", InlineConfirmDialog))
            return
        elif isinstance(pending, SecretsInputRequest):
            self.push_screen(
                SecretsInputDialog(
                    service=pending.service,
                    keys=pending.keys,
                    reason=pending.reason,
                ),
                finish,
            )

    def _dismiss_permission_prompt(self) -> None:
        self._local_pending = None
        self._unlock_prompt_input()
        prompt = self.query("#permission-prompt")
        if prompt:
            prompt.remove()

    def _respond_to_plan(self, response: PermissionResponse) -> None:
        pending = self.session.pending_event
        if pending is None or not isinstance(pending, PlanReady):
            return
        status = "approved" if response.kind == "approve" else "denied"
        self.session.dispatch_activity(
            {
                "type": "plan_resolved",
                "request_id": pending.id,
                "status": status,
            }
        )
        self.session.respond(pending.id, response)
        self._local_pending = None
        self._unlock_prompt_input()

    def on_permission_answered(self, message: PermissionAnswered) -> None:
        pending = self.session.pending_event
        if pending is not None and isinstance(pending, PermissionRequest):
            self.session.respond(pending.id, message.response)
        self._dismiss_permission_prompt()

    def _dismiss_inline_confirm(self) -> None:
        self._local_pending = None
        self._unlock_prompt_input()
        widget = self.query("#inline-confirm")
        if widget:
            widget.remove()

    def on_inline_confirm_answered(self, message: InlineConfirmAnswered) -> None:
        pending = self.session.pending_event
        if pending is not None and isinstance(pending, TypedConfirmRequest):
            self.session.respond(pending.id, message.response)
        self._dismiss_inline_confirm()

    def _stop_log_pane(self) -> None:
        if self._log_controller is not None:
            self._log_controller.set()
            self._log_controller = None
        if self._active_log_pane is not None:
            self.pop_screen()
            self._active_log_pane = None
        self._log_lines = []

    def _start_log_pane(self, stack_name: str, service: str | None = None) -> None:
        yaml_path = stack_state_yaml_path(stack_name, self._cwd)
        if not Path(yaml_path).exists():
            self.session.dispatch_activity(
                {
                    "type": "user_text",
                    "text": f"/logs {stack_name}{f' {service}' if service else ''}",
                }
            )
            self.session.dispatch_activity(
                {"type": "error", "error": RuntimeError(f"stack {stack_name} not found")}
            )
            return
        self._stop_log_pane()
        controller = asyncio.Event()
        self._log_controller = controller
        self._log_lines = []
        pane = LogPane(stack_name=stack_name, service=service, lines=[])
        self._active_log_pane = pane
        self.push_screen(pane)
        secret_keys = collect_secret_keys(
            stack_name,
            SecretKeysContext(cwd=self._cwd, state_store=self._state_store),
        )
        bound = self._compose_runner.for_stack(stack_name, yaml_path)

        async def follow_logs() -> None:
            try:
                async for chunk in bound.logs(
                    follow=True,
                    tail_lines=50,
                    signal=controller,
                    service=service,
                ):
                    if controller.is_set():
                        break
                    scrubbed = scrub_line(chunk, secret_keys)
                    self._log_lines.append(scrubbed)
                    if len(self._log_lines) > 200:
                        self._log_lines = self._log_lines[-200:]
                    if self._active_log_pane is not None:
                        self._active_log_pane.append_line(scrubbed)
            except Exception:
                return

        asyncio.create_task(follow_logs())

    async def _resolve_all_providers(self) -> dict[ProviderName, Any]:
        return {
            name: resolve_provider_for_request(
                name, os.environ, api_key_store=self.api_key_store
            )
            for name in PROVIDER_NAMES
        }

    async def _open_provider_connect(self) -> None:
        instances = await self._resolve_all_providers()
        statuses = await get_provider_statuses(
            api_key_store=self.api_key_store,
            providers=instances,
        )
        api_key_statuses = await describe_api_key_status(self.api_key_store, os.environ)
        provider = await self.push_screen_wait(
            ProviderConnectDialog(
                statuses=statuses,
                api_key_statuses=api_key_statuses,
            )
        )
        if provider is None:
            return
        status = next((s for s in statuses if s.provider == provider), None)
        if status and status.connected:
            await self._open_model_picker(provider)
        else:
            await self._on_connect_provider(provider)

    async def _build_model_picker_rows(
        self, scope_provider: str | None = None
    ) -> list[Any]:
        instances = await self._resolve_all_providers()
        statuses = await get_provider_statuses(
            api_key_store=self.api_key_store,
            providers=instances,
        )
        catalog = await build_model_catalog(statuses)
        rows = flatten_catalog(catalog)
        if scope_provider:
            rows = [
                row
                for row in rows
                if (row.kind == "header" and row.provider == scope_provider)
                or (row.kind != "header" and row.provider == scope_provider)
            ]
        return rows

    def _prompt_input(self) -> Input | None:
        try:
            return self.query_one("#prompt-input", Input)
        except Exception:
            return None

    def _lock_prompt_input(self) -> None:
        prompt_input = self._prompt_input()
        if prompt_input is not None:
            prompt_input.disabled = True

    def _unlock_prompt_input(self) -> None:
        prompt_input = self._prompt_input()
        if prompt_input is None:
            return
        prompt_input.disabled = False
        prompt_input.focus()

    async def _open_model_picker(self, scope_provider: str | None = None) -> None:
        self._lock_prompt_input()
        loading = Static("Loading models…", id="model-picker-loading")
        self.mount(loading, after="#prompt")
        try:
            rows = await self._build_model_picker_rows(scope_provider)
        finally:
            if loading.is_attached:
                loading.remove()

        has_navigable = any(row.kind in {"model", "connect"} for row in rows)
        if not has_navigable:
            self._unlock_prompt_input()
            self.session.dispatch_activity(
                {
                    "type": "error",
                    "error": RuntimeError("No providers connected. Use /connect first."),
                }
            )
            await self._open_provider_connect()
            return

        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        self._model_picker_waiter = waiter
        panel = ModelPickerDialog(
            rows=rows,
            current={
                "provider": self.active_provider_name,
                "model": self.active_model or "",
            },
            id="model-picker",
        )
        self.mount(panel, after="#prompt")
        self.set_focus(panel)
        try:
            choice = await waiter
        finally:
            self._model_picker_waiter = None
            if panel.is_attached:
                panel.remove()
            self._unlock_prompt_input()

        if choice is None:
            self.session.dispatch_activity(
                {"type": "assistant_text", "delta": "Model selection cancelled"}
            )
            return
        if isinstance(choice, ModelChoice):
            self._on_model_picked(choice)
        elif choice == "connect":
            await self._open_provider_connect()
        else:
            await self._on_connect_provider(choice)

    def _on_model_picked(self, choice: ModelChoice) -> None:
        try:
            self.engine.provider = resolve_provider_for_request(
                choice.provider, os.environ, api_key_store=self.api_key_store
            )
            self.engine.model = choice.model
            self.active_provider_name = choice.provider
            self.active_model = choice.model
            self.session.dispatch_activity(
                {
                    "type": "assistant_text",
                    "delta": f"Model set to {choice.model} ({choice.provider})",
                }
            )
        except Exception as err:  # noqa: BLE001
            self.session.dispatch_activity(
                {"type": "error", "error": err}
            )

    async def _on_connect_provider(self, provider: str | None = None) -> None:
        if provider and is_api_key_provider_name(provider):
            result = await self.push_screen_wait(
                ApiKeyInputDialog(
                    provider=provider,  # type: ignore[arg-type]
                    env_var_name=api_key_env_var(provider),  # type: ignore[arg-type]
                )
            )
            if result:
                await self._on_api_key_submit(
                    cast(ApiKeyProviderName, provider),
                    result,
                    return_to="modelPicker",
                )
            return
        if provider == "ollama":
            host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
            ollama_result = await self.push_screen_wait(OllamaSetupDialog(host=host))
            if ollama_result is not None:
                os.environ["OLLAMA_HOST"] = ollama_result.host
            return
        await self._open_provider_connect()

    async def _on_api_key_submit(
        self,
        provider: ApiKeyProviderName,
        value: str,
        *,
        return_to: str | None = None,
    ) -> None:
        try:
            await self.api_key_store.set(provider, value)
            os.environ[api_key_env_var(provider)] = value
            self.session.dispatch_activity(
                {"type": "assistant_text", "delta": f"API key saved for {provider}"}
            )
            if return_to == "modelPicker":
                await self._open_model_picker(provider)
        except Exception as err:  # noqa: BLE001
            self.session.dispatch_activity({"type": "error", "error": err})

    def _slash_deps(self, input_text: str = "") -> SlashEffectApplierDeps:
        return SlashEffectApplierDeps(
            input=input_text,
            session=self.session,
            engine=self.engine,
            api_key_store=self.api_key_store,
            session_store=self._session_store,
            exit=self.exit,
            stop_log_pane=self._stop_log_pane,
            set_show_details=lambda value: setattr(self, "show_details", value),
            set_show_palette=lambda value: setattr(self, "show_palette", value),
            set_show_queue=lambda value: setattr(self, "show_queue", value),
            set_timeline_key=lambda _value: setattr(
                self, "_timeline_key", self._timeline_key + 1
            ),
            set_active_provider_name=lambda value: setattr(
                self, "active_provider_name", value
            ),
            set_active_model=lambda value: setattr(self, "active_model", value),
            open_provider_connect=self._open_provider_connect,
            open_model_picker=self._open_model_picker,
            start_log_pane=self._start_log_pane,
        )

    async def _handle_submit(self, input_text: str) -> None:
        target = input_text.strip()
        lowered = target.lower()
        if lowered in {"exit", "/exit"}:
            self.session.cancel_current()
            self.exit()
            return
        if target.startswith("/"):
            result = await route_slash_command(
                input_text,
                SlashRouterContext(
                    cwd=self._cwd,
                    state_store=self._state_store,
                    active_provider_name=self.active_provider_name,  # type: ignore[arg-type]
                    api_key_store=self.api_key_store,
                    session_store=self._session_store,
                ),
            )
            await apply_slash_effects(result.effects, self._slash_deps(input_text))
            self._refresh_ui()
            if result.handled:
                return
        self.session.submit(target)
        self._refresh_ui()

    def on_model_picker_closed(self, message: ModelPickerClosed) -> None:
        if self._model_picker_waiter is not None and not self._model_picker_waiter.done():
            self._model_picker_waiter.set_result(message.result)

    @work(exclusive=False, name="submit")
    async def _submit_prompt(self, text: str) -> None:
        await self._handle_submit(text)

    def on_prompt_submitted(self, message: PromptSubmitted) -> None:
        if self._input_blocked():
            return
        self._submit_prompt(message.text)

    async def on_resume_queue(self, _message: ResumeQueue) -> None:
        self.session.resume_queue()

    def _input_blocked(self) -> bool:
        return (
            self.session.interaction.phase in {"awaiting_input"}
            or self.session.pending_event is not None
            or self._local_pending is not None
            or self._model_picker_waiter is not None
            or self.show_palette
            or self.show_queue
            or (self.show_details and self._latest_tool() is not None)
            or self._active_log_pane is not None
        )

    def action_cancel(self) -> None:
        if self._active_log_pane is not None:
            self._stop_log_pane()
        elif self._local_pending == "permission":
            pending = self.session.pending_event
            if pending is not None and isinstance(pending, PermissionRequest):
                from docker_agent.types.permissions import Deny

                self.session.respond(pending.id, Deny())
            self._dismiss_permission_prompt()
        elif self._local_pending == "confirm":
            pending = self.session.pending_event
            if pending is not None and isinstance(pending, TypedConfirmRequest):
                from docker_agent.types.permissions import Deny

                self.session.respond(pending.id, Deny())
            self._dismiss_inline_confirm()
        elif self._local_pending is not None:
            self._local_pending = None
        else:
            self.session.cancel_current()

    async def action_toggle_details(self) -> None:
        if self.session.pending_event or self._local_pending or self._active_log_pane:
            return
        latest = self._latest_tool()
        if latest is None:
            return
        self.show_palette = False
        self.show_queue = False
        self.show_details = not self.show_details
        existing = self.query("#tool-details")
        if self.show_details and not existing:
            self.mount(ToolDetailsPanel(activity=latest, id="tool-details"))
        elif not self.show_details and existing:
            existing.remove()

    @work(exclusive=True)
    async def action_toggle_palette(self) -> None:
        if self.session.pending_event or self._local_pending or self._active_log_pane:
            return
        self.show_details = False
        self.show_queue = False
        registry = create_default_registry()
        registry.register(
            Command(
                id="cancel",
                title="Cancel",
                description="Cancel current turn",
                shortcut="Ctrl+C",
                action=self.session.cancel_current,
            )
        )
        command = await self.push_screen_wait(CommandPalette(commands=registry.get_all()))
        if command is None:
            return
        if command.action is not None:
            command.action()
        elif command.insert_text:
            self.query_one("#prompt", PromptInput).prefill = command.insert_text

    @work(exclusive=True)
    async def action_toggle_queue(self) -> None:
        if self.session.pending_event or self._local_pending or self._active_log_pane:
            return
        self.show_details = False
        self.show_palette = False
        action = await self.push_screen_wait(
            QueuePanel(
                queue=self.session.interaction.queue,
                on_remove=self.session.remove_queued,
                on_clear=self.session.clear_queue,
                on_resume=self.session.resume_queue,
            )
        )
        if action is not None and action.kind == "resume":
            self.session.resume_queue()

    async def on_key(self, event: events.Key) -> None:
        if event.key == "escape" and self._active_log_pane is not None:
            self._stop_log_pane()
            event.stop()
            return
        if self._local_pending == "permission" and event.key.lower() in ("y", "n", "a"):
            try:
                panel = self.query_one("#permission-prompt", PermissionDialog)
                panel.on_key(event)
                event.stop()
            except Exception:
                pass
        elif self._local_pending == "confirm" and event.key.lower() in ("y", "n"):
            try:
                panel = self.query_one("#inline-confirm", InlineConfirmDialog)
                panel.on_key(event)
                event.stop()
            except Exception:
                pass
        elif self._local_pending == "plan":
            pending = self.session.pending_event
            if isinstance(pending, PlanReady):
                key = event.key.lower()
                if key == "y":
                    self._respond_to_plan(Approve())
                    event.stop()
                elif key == "n":
                    self._respond_to_plan(Deny())
                    event.stop()
                elif key == "x":
                    self.session.dispatch_activity(
                        {"type": "plan_toggle_yaml", "request_id": pending.id}
                    )
                    event.stop()
                elif key == "c":
                    self.session.dispatch_activity(
                        {"type": "plan_toggle_config", "request_id": pending.id}
                    )
                    event.stop()


__all__ = ["REPL"]