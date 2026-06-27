"""Parity tests for tool_presentation — mirrors src/ui/__tests__/toolPresentation.test.ts."""

from __future__ import annotations

import pytest

from docker_agent.ui.tool_presentation import present_tool, sanitize_tool_text


@pytest.mark.parametrize(
    ("name", "input_value", "output", "expected_title", "expected_summary", "detail_check"),
    [
        (
            "plan_stack",
            {
                "stackName": "web",
                "intent": "deploy web app",
                "services": {"app": {"image": "nginx"}},
            },
            {
                "blocked": False,
                "composeYaml": "services:\n  app:\n    image: nginx\n",
                "diff": {"stackName": "web", "status": "missing", "serviceDiffs": []},
            },
            "Plan stack: web",
            "Generate Compose plan for web (deploy web app)",
            lambda detail: any("nginx" in line for line in detail),
        ),
        (
            "apply_stack",
            {"stackName": "web", "composeYaml": "services:\n  app:\n    image: nginx\n"},
            {"ok": True, "exitCode": 0, "yamlPath": "/path/to/web.yaml", "healthy": True},
            "Apply stack: web",
            "Deploy stack web",
            lambda detail: any("healthy" in line for line in detail),
        ),
        (
            "destroy_stack",
            {"stackName": "web", "removeVolumes": True},
            {"ok": True, "exitCode": 0},
            "Destroy stack: web",
            "Tear down stack web (volumes removed)",
            lambda detail: any("exitCode" in line for line in detail),
        ),
        (
            "destroy_all_stacks",
            {"removeVolumes": False},
            {"destroyed": ["web"], "failed": []},
            "Destroy all stacks",
            "Tear down all stacks",
            lambda detail: any("web" in line for line in detail),
        ),
        (
            "list_stacks",
            {},
            {"stacks": [{"name": "web", "createdAt": "2024-01-01", "services": ["app"]}]},
            "List stacks",
            "List all stacks",
            lambda detail: any("web" in line for line in detail),
        ),
        (
            "inspect_drift",
            {"stackName": "web"},
            {"stackName": "web", "status": "in_sync", "serviceDiffs": []},
            "Inspect drift: web",
            "Compare desired vs actual for web",
            None,
        ),
        (
            "remediate_drift",
            {"stackName": "web"},
            {
                "diff": {"stackName": "web", "status": "drift", "serviceDiffs": []},
                "desiredYaml": "yaml",
                "remediable": True,
            },
            "Remediate drift: web",
            "Detect drift and prepare remediation for web",
            lambda detail: any("remediable" in line for line in detail),
        ),
        (
            "get_stack_status",
            {"stackName": "web", "tailLines": 50},
            {"rows": [{"Name": "web_app_1", "State": "running"}], "logTail": "log line\n"},
            "Stack status: web",
            "Container state and logs for web",
            lambda detail: any("running" in line for line in detail),
        ),
        (
            "get_logs",
            {"stackName": "web", "service": "app", "tailLines": 100},
            {"logTail": "log line\n", "lineCount": 1, "truncated": False},
            "Logs: web/app",
            "Fetch logs for web (service: app)",
            lambda detail: any("lineCount" in line for line in detail),
        ),
        (
            "get_health",
            {"stackName": "web"},
            {
                "containers": [
                    {
                        "name": "web_app_1",
                        "service": "app",
                        "status": "running",
                        "cpuPercent": 5,
                        "memUsedMb": 100,
                        "memLimitMb": 512,
                        "memPercent": 19.5,
                        "restartCount": 0,
                        "crashLoop": False,
                    }
                ],
                "crashLoops": [],
            },
            "Health: web",
            "Per-container health and stats for web",
            lambda detail: any("running" in line for line in detail),
        ),
        (
            "pull_image",
            {"image": "nginx:latest"},
            {"ok": True, "status": "valid", "source": "pulled"},
            "Pull image: nginx:latest",
            "Validate and pull nginx:latest",
            lambda detail: any("pulled" in line for line in detail),
        ),
        (
            "exec_docker",
            {"args": ["ps", "-a"]},
            {"exitCode": 0, "stdout": "CONTAINER ID...", "stderr": ""},
            "Docker: ps -a",
            "Run docker ps -a",
            lambda detail: any("stdout" in line for line in detail),
        ),
    ],
)
def test_registers_presentation_for_tool(
    name: str,
    input_value: dict[str, object],
    output: dict[str, object],
    expected_title: str,
    expected_summary: str,
    detail_check,
) -> None:
    presentation = present_tool(name, input_value, output)
    assert presentation.title == expected_title
    assert presentation.summary == expected_summary
    if detail_check is not None:
        assert detail_check(presentation.detail_lines)


def test_falls_back_for_unknown_tool_name() -> None:
    presentation = present_tool("unknown_tool", {"foo": "bar"}, {"result": 1})
    assert presentation.title == "Tool: unknown_tool"
    assert presentation.summary == "Run unknown_tool"
    assert len(presentation.detail_lines) > 0


def test_does_not_expose_credentials_in_titles_or_summaries() -> None:
    presentation = present_tool(
        "exec_docker",
        {"args": ["login", "--password", "hunter2"]},
    )
    assert "hunter2" not in presentation.title
    assert "hunter2" not in presentation.summary


def test_truncates_detail_lines_to_20_lines() -> None:
    long_output = "\n".join(f"line {index}" for index in range(50))
    presentation = present_tool(
        "exec_docker",
        {"args": ["logs", "c"]},
        {"exitCode": 0, "stdout": long_output, "stderr": ""},
    )
    assert len(presentation.detail_lines) <= 20


def test_truncates_detail_bytes_to_4096() -> None:
    long_output = "x" * 10_000
    presentation = present_tool(
        "exec_docker",
        {"args": ["logs", "c"]},
        {"exitCode": 0, "stdout": long_output, "stderr": ""},
    )
    total = len("\n".join(presentation.detail_lines))
    assert total <= 4096


def test_masks_secret_like_keys_in_detail() -> None:
    presentation = present_tool(
        "plan_stack",
        {
            "stackName": "web",
            "services": {
                "app": {
                    "image": "x",
                    "environment": {
                        "apiKey": "super-secret",
                        "password": "hunter2",
                        "token": "tok",
                        "secret": "sec",
                        "credential": "cred",
                    },
                }
            },
        },
    )
    text = "\n".join(presentation.detail_lines)
    assert "super-secret" not in text
    assert "hunter2" not in text
    assert "tok" not in text
    assert "sec" not in text
    assert "cred" not in text
    assert "***" in text


def test_sanitize_tool_text_masks_secret_like_keys_case_insensitively() -> None:
    import json

    text = json.dumps(
        {
            "APIKEY": "abc",
            "MyPassword": "def",
            "token": "ghi",
            "SECRET_VALUE": "jkl",
            "someCredential": "mno",
        }
    )
    sanitized = sanitize_tool_text(text)
    assert "abc" not in sanitized
    assert "def" not in sanitized
    assert "ghi" not in sanitized
    assert "jkl" not in sanitized
    assert "mno" not in sanitized


def test_sanitize_tool_text_preserves_yaml_key_after_secret_like_key_name() -> None:
    yaml_text = "\n".join(
        [
            "addedKeys:",
            "  - MARIADB_ROOT_PASSWORD",
            "services:",
            "  web:",
            "    image: nginx",
        ]
    )
    assert "\nservices:\n" in sanitize_tool_text(yaml_text)


def test_sanitize_tool_text_truncates_to_4096_bytes() -> None:
    long = "a" * 10_000
    sanitized = sanitize_tool_text(long)
    assert len(sanitized.encode("utf-8")) <= 4096