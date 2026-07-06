from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from docker_agent.mcp.approval import handle_pending_confirmation


class _FakeTool:
    def __init__(self, name: str, result: Any) -> None:
        self.name = name
        self.result = result
        self.ainvoke = AsyncMock(return_value=result)


@pytest.mark.asyncio
async def test_handle_pending_plan_confirmation_approves_via_confirm_tool(
    make_loop_ctx,
) -> None:
    ctx = make_loop_ctx()
    pending = {
        "status": "pending_confirmation",
        "pending_action": {
            "id": "pending-1",
            "session_id": "session-a",
            "cwd": ctx.cwd,
            "tool": "docker.deploy_stack",
            "kind": "plan_review",
            "display": {
                "artifacts": [
                    {
                        "kind": "manifest",
                        "label": "Compose YAML",
                        "language": "yaml",
                        "content": "services: {}",
                    },
                    {"kind": "diff", "label": "Stack diff", "content": {"serviceDiffs": []}},
                ]
            },
        },
    }
    confirm_tool = _FakeTool(
        "docker.confirm_action",
        {"status": "ok", "result": "Stack applied."},
    )

    result = await handle_pending_confirmation(
        pending,
        tools_by_name={"docker.confirm_action": confirm_tool},
        ctx=ctx,
    )

    assert result == {"status": "ok", "result": "Stack applied."}
    ctx.request_confirm.assert_awaited_once_with(pending["pending_action"]["display"])
    confirm_tool.ainvoke.assert_awaited_once_with(
        {
            "pending_action_id": "pending-1",
            "session_id": "session-a",
            "cwd": ctx.cwd,
            "decision": "approve",
            "typed_phrase": None,
            "secrets": None,
        }
    )


@pytest.mark.asyncio
async def test_handle_pending_typed_confirmation_denies_on_wrong_phrase(
    make_loop_ctx,
) -> None:
    ctx = make_loop_ctx()
    ctx.request_typed_confirm.return_value = {
        "kind": "typed_confirm_value",
        "value": "WRONG",
    }
    pending = {
        "status": "pending_confirmation",
        "pending_action": {
            "id": "pending-1",
            "session_id": "session-a",
            "cwd": ctx.cwd,
            "tool": "docker.destroy_stack",
            "kind": "typed",
            "display": {
                "phrase": "DESTROY web",
                "reason": "Destroy web and delete its volumes.",
            },
        },
    }
    confirm_tool = _FakeTool("docker.confirm_action", {"status": "ok", "result": "denied"})

    result = await handle_pending_confirmation(
        pending,
        tools_by_name={"docker.confirm_action": confirm_tool},
        ctx=ctx,
    )

    assert result == {"status": "ok", "result": "denied"}
    confirm_tool.ainvoke.assert_awaited_once()
    assert confirm_tool.ainvoke.await_args.args[0]["decision"] == "deny"


@pytest.mark.asyncio
async def test_handle_pending_confirmation_accepts_mcp_text_content(
    make_loop_ctx,
) -> None:
    ctx = make_loop_ctx()
    pending = {
        "status": "pending_confirmation",
        "pending_action": {
            "id": "pending-1",
            "session_id": "session-a",
            "cwd": ctx.cwd,
            "tool": "docker.deploy_stack",
            "kind": "plan_review",
            "display": {
                "artifacts": [
                    {
                        "kind": "manifest",
                        "label": "Compose YAML",
                        "language": "yaml",
                        "content": "services: {}",
                    },
                    {"kind": "diff", "label": "Stack diff", "content": {"serviceDiffs": []}},
                ]
            },
        },
    }
    confirm_tool = _FakeTool(
        "docker.confirm_action",
        {"status": "ok", "result": "Stack applied."},
    )

    result = await handle_pending_confirmation(
        [{"type": "text", "text": json.dumps(pending)}],
        tools_by_name={"docker.confirm_action": confirm_tool},
        ctx=ctx,
    )

    assert result == {"status": "ok", "result": "Stack applied."}
    confirm_tool.ainvoke.assert_awaited_once()
