from __future__ import annotations

import json
from typing import Any

import pytest

from docker_agent.mcp.capabilities import (
    load_mcp_capabilities,
    mcp_command_specs,
    mcp_context_summary,
    mcp_high_risk_tool_names,
    model_visible_mcp_tools,
)


class _FakeMcpTool:
    description = "fake MCP tool"

    def __init__(self, name: str, result: Any, metadata: dict[str, Any] | None = None) -> None:
        self.name = name
        self.result = result
        self.metadata = metadata or {}
        self.calls: list[dict[str, Any]] = []

    async def ainvoke(self, input_data: dict[str, Any]) -> Any:
        self.calls.append(input_data)
        return self.result


@pytest.mark.asyncio
async def test_load_mcp_capabilities_merges_all_plugin_capability_tools() -> None:
    docker_caps = _FakeMcpTool(
        "docker.capabilities",
        {
            "tools": [
                {
                    "namespace": "docker",
                    "name": "docker.deploy_stack",
                    "risk": "high",
                    "mutating": True,
                },
                {"namespace": "docker", "name": "docker.commit_action", "operation": "commit"},
            ],
            "commands": [{"pattern": "^docker ps$", "tool": "docker.list_stacks"}],
            "context": {
                "summarize_tool": "docker.summarize_context",
                "list_resources_tool": "docker.list_resources",
            },
        },
    )
    k8s_caps = _FakeMcpTool(
        "k8s.capabilities",
        {
            "tools": [
                {"namespace": "k8s", "name": "k8s.deploy", "risk": "high", "mutating": True},
                {"namespace": "k8s", "name": "k8s.commit_action", "operation": "commit"},
            ],
            "commands": [{"pattern": "^pods$", "tool": "k8s.list_pods"}],
            "context": {
                "summarize_tool": "k8s.summarize_context",
                "list_resources_tool": "k8s.list_resources",
            },
        },
    )

    capabilities = await load_mcp_capabilities([docker_caps, k8s_caps])

    assert sorted(capabilities["plugins"]) == ["docker", "k8s"]
    assert [tool["name"] for tool in capabilities["tools"]] == [
        "docker.deploy_stack",
        "docker.commit_action",
        "k8s.deploy",
        "k8s.commit_action",
    ]
    assert [spec.tool for spec in mcp_command_specs(capabilities)] == [
        "docker.list_stacks",
        "k8s.list_pods",
    ]
    assert capabilities["context"]["summarize_tools"] == [
        "docker.summarize_context",
        "k8s.summarize_context",
    ]
    assert capabilities["context"]["list_resources_tools"] == [
        "docker.list_resources",
        "k8s.list_resources",
    ]


@pytest.mark.asyncio
async def test_load_mcp_capabilities_rejects_duplicate_tool_names() -> None:
    first = _FakeMcpTool(
        "docker.capabilities",
        {"tools": [{"namespace": "docker", "name": "docker.deploy"}]},
    )
    second = _FakeMcpTool(
        "k8s.capabilities",
        {"tools": [{"namespace": "k8s", "name": "docker.deploy"}]},
    )

    with pytest.raises(ValueError, match="Duplicate MCP tool capability"):
        await load_mcp_capabilities([first, second])


@pytest.mark.asyncio
async def test_mcp_context_summary_joins_all_plugin_summaries() -> None:
    capabilities = {
        "context": {"summarize_tools": ["docker.summarize_context", "k8s.summarize_context"]}
    }
    docker_summary = _FakeMcpTool("docker.summarize_context", {"summary": "Docker stacks: web"})
    k8s_summary = _FakeMcpTool("k8s.summarize_context", {"summary": "K8s contexts: dev"})

    summary = await mcp_context_summary(
        [docker_summary, k8s_summary],
        capabilities=capabilities,
        cwd="C:/repo",
        fallback="fallback",
    )

    assert summary == "Docker stacks: web\n\nK8s contexts: dev"
    assert docker_summary.calls == [{"cwd": "C:/repo"}]
    assert k8s_summary.calls == [{"cwd": "C:/repo"}]


def test_model_visible_and_high_risk_tools_use_merged_capabilities() -> None:
    capabilities = {
        "tools": [
            {"name": "docker.deploy_stack", "risk": "high", "mutating": True},
            {"name": "docker.commit_action", "operation": "commit"},
            {"name": "k8s.deploy", "risk": "high", "mutating": True},
            {"name": "k8s.rollback_action", "operation": "rollback"},
        ]
    }
    tools = [
        _FakeMcpTool("docker.deploy_stack", {}),
        _FakeMcpTool("docker.commit_action", {}),
        _FakeMcpTool("k8s.deploy", {}),
        _FakeMcpTool("k8s.rollback_action", {}),
    ]

    assert [tool.name for tool in model_visible_mcp_tools(tools, capabilities=capabilities)] == [
        "docker.deploy_stack",
        "k8s.deploy",
    ]
    assert mcp_high_risk_tool_names(tools, capabilities) == {
        "docker.deploy_stack",
        "k8s.deploy",
    }


@pytest.mark.asyncio
async def test_capability_payload_may_be_text_wrapped_json() -> None:
    tool = _FakeMcpTool(
        "docker.capabilities",
        [{"type": "text", "text": json.dumps({"tools": [{"name": "docker.list"}]})}],
    )

    assert await load_mcp_capabilities([tool]) == {
        "plugins": {"docker": {"tools": [{"name": "docker.list"}]}},
        "tools": [{"name": "docker.list"}],
        "commands": [],
        "context": {"summarize_tools": [], "list_resources_tools": []},
    }
