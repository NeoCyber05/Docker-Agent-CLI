"""Integration plan-flow parity — mirrors tests/integration/plan-flow.test.ts."""

from __future__ import annotations

from typing import Any

import pytest

from src.services.api.types import (
    MessageStopEvent,
    ToolUseDeltaEvent,
    ToolUseStartEvent,
    ToolUseStopEvent,
)
from src.types.permissions import Approve, TypedConfirmValue
from src.types.stack import DockerAgentMeta, ServiceSpec, StackDefinition
from tests.integration.conftest import plan_stack_events


def _seed_stack(state_store: Any, name: str) -> None:
    state_store.write(
        name,
        StackDefinition(
            x_docker_agent=DockerAgentMeta(
                name=name,
                createdAt="x",
                lastApplied="x",
                intent="x",
                provider="x",
                generatedBy="x",
                envFileSources={},
            ),
            services={"web": ServiceSpec(image="nginx:1.27")},
        ),
    )


@pytest.mark.asyncio
async def test_nginx_plan_confirm_apply(make_engine, compose_runner, tmp_project) -> None:
    compose_runner.on_bound_runner_created = lambda runner: runner.set_running_services(["web"])
    engine = make_engine(
        [
            plan_stack_events(
                {
                    "stackName": "nginx",
                    "intent": "tao nginx",
                    "services": [
                        {
                            "name": "web",
                            "kind": "custom",
                            "image": "nginx:1.27-alpine",
                            "exposure": "public",
                            "hostPort": 8080,
                            "containerPort": 80,
                        }
                    ],
                }
            ),
        ]
    )
    events: list[str] = []

    async for ev in engine.query("tao nginx"):
        events.append(ev.type)
        if ev.type == "plan_ready":
            engine.respond_to(ev.id, Approve())

    assert "plan_ready" in events
    assert compose_runner.for_stack_calls[0]["stack_name"] == "nginx"
    assert compose_runner.bound_for("nginx").cwd == str(tmp_project)
    assert compose_runner.bound_for("nginx").up_calls[0] == {"detach": True, "scale": None}
    assert (tmp_project / "docker-stacks" / "nginx.yaml").exists()


@pytest.mark.asyncio
async def test_postgres_auto_generates_secret_file(make_engine, tmp_project) -> None:
    engine = make_engine(
        [
            plan_stack_events(
                {
                    "stackName": "pg",
                    "intent": "tao postgres",
                    "services": [
                        {
                            "name": "db",
                            "kind": "catalog",
                            "catalogId": "postgresql:16",
                        }
                    ],
                }
            ),
        ]
    )
    auto_generated_secrets: list[dict[str, object]] = []

    async for ev in engine.query("tao postgres"):
        if ev.type == "plan_ready":
            auto_generated_secrets = [
                {"service": s.service, "keys": s.keys} for s in (ev.auto_generated_secrets or [])
            ]
            engine.respond_to(ev.id, Approve())

    assert {"service": "db", "keys": ["POSTGRES_PASSWORD"]} in auto_generated_secrets
    secret_path = tmp_project / ".docker-agent" / "secrets" / "pg-db.env"
    secret_file = secret_path.read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD=" in secret_file
    assert len(secret_file.split("POSTGRES_PASSWORD=", 1)[1].strip()) >= 20


@pytest.mark.asyncio
async def test_destroy_all_aborts_without_typed_destroy_all(
    make_engine, compose_runner, state_store, tmp_project
) -> None:
    _seed_stack(state_store, "webapp")
    stack_path = tmp_project / "docker-stacks" / "webapp.yaml"
    engine = make_engine(
        [
            [
                ToolUseStartEvent(id="t1", name="destroy_all_stacks"),
                ToolUseDeltaEvent(id="t1", args_partial_json="{}"),
                ToolUseStopEvent(id="t1"),
                MessageStopEvent(stop_reason="tool_use"),
            ],
            [MessageStopEvent(stop_reason="end_turn")],
        ]
    )
    typed_confirm_requested = False

    async for ev in engine.query("destroy all"):
        if ev.type == "typed_confirm_request":
            typed_confirm_requested = True
            engine.respond_to(ev.id, TypedConfirmValue(value="nope"))

    assert typed_confirm_requested is True
    assert compose_runner.for_stack_calls == []
    assert stack_path.exists()


@pytest.mark.asyncio
async def test_rollback_started_includes_running_services_on_partial_failure(
    make_engine, compose_runner
) -> None:
    from src.services.docker.compose_runner import ComposePsRow

    def on_bound(runner: Any) -> None:
        async def failing_up(**_kwargs: object):
            yield "partial failure\n"
            runner.last_exit_code = 1

        runner.up = failing_up  # type: ignore[method-assign]
        runner.ps_rows = [ComposePsRow(name="partial-web-1", service="web", state="running")]

    compose_runner.on_bound_runner_created = on_bound

    engine = make_engine(
        [
            plan_stack_events(
                {
                    "stackName": "partial",
                    "intent": "deploy partial",
                    "services": [
                        {
                            "name": "web",
                            "kind": "custom",
                            "image": "nginx:1.27",
                            "exposure": "public",
                            "hostPort": 8080,
                            "containerPort": 80,
                        },
                        {
                            "name": "db",
                            "kind": "catalog",
                            "catalogId": "postgresql:16",
                        },
                    ],
                }
            ),
            [MessageStopEvent(stop_reason="end_turn")],
        ]
    )

    rollback_events: list[Any] = []

    async for ev in engine.query("deploy partial"):
        if ev.type == "plan_ready":
            engine.respond_to(ev.id, Approve())
        if ev.type == "rollback_started":
            rollback_events.append(ev)

    assert len(rollback_events) == 1
    assert rollback_events[0].running_services == ["web"]