"""Parity tests for activity â€” mirrors src/ui/__tests__/activity.test.ts."""

from __future__ import annotations

from docker_agent.types.message import (
    AssistantBlock,
    AssistantMessage,
    ToolResultMessage,
    UserMessage,
)
from docker_agent.ui.activity import (
    ActivityState,
    activity_reducer,
    project_messages_to_activities,
)


def make_state(**overrides: object) -> ActivityState:
    state = ActivityState()
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def test_tool_call_progress_result_lifecycle() -> None:
    state = make_state()
    state = activity_reducer(state, {"type": "tool_call", "name": "list_stacks", "input": {}})
    assert len(state.items) == 1
    tool = state.items[0]
    assert tool.type == "tool"
    assert tool.status == "running"
    assert state.active_tool_activity_id == tool.id

    state = activity_reducer(state, {"type": "tool_progress", "msg": "Listing stacks..."})
    tool = state.items[0]
    assert tool.type == "tool"
    assert "Listing stacks..." in tool.progress_msgs

    state = activity_reducer(
        state,
        {"type": "tool_result", "name": "list_stacks", "output": {"stacks": []}},
    )
    tool = state.items[0]
    assert tool.type == "tool"
    assert tool.status == "completed"
    assert state.active_tool_activity_id is None


def test_marks_explicit_unsuccessful_tool_output_as_failed() -> None:
    state = activity_reducer(
        make_state(),
        {"type": "tool_call", "name": "apply_stack", "input": {"stackName": "web"}},
    )
    state = activity_reducer(
        state,
        {
            "type": "tool_result",
            "name": "apply_stack",
            "output": {"ok": False, "exitCode": 1, "errorOutput": "compose failed"},
        },
    )
    tool = state.items[0]
    assert tool.type == "tool"
    assert tool.status == "failed"


def test_bounds_combined_tool_input_and_output_details() -> None:
    state = activity_reducer(
        make_state(),
        {
            "type": "tool_call",
            "name": "exec_docker",
            "input": {"args": ["logs", "container"]},
        },
    )
    state = activity_reducer(
        state,
        {
            "type": "tool_result",
            "name": "exec_docker",
            "output": {f"field{i}": f"value{i}" for i in range(20)},
        },
    )
    tool = state.items[0]
    assert tool.type == "tool"
    details = tool.detail_lines
    assert len(details) <= 20
    assert len("\n".join(details).encode("utf-8")) <= 4096


def test_sanitizes_and_bounds_tool_progress() -> None:
    state = activity_reducer(
        make_state(),
        {"type": "tool_call", "name": "pull_image", "input": {"image": "nginx"}},
    )
    for index in range(30):
        state = activity_reducer(
            state,
            {
                "type": "tool_progress",
                "msg": f"step {index} token=very-secret-token {'x' * 300}",
            },
        )
    tool = state.items[0]
    assert tool.type == "tool"
    progress = tool.progress_msgs
    assert len(progress) <= 20
    assert len("\n".join(progress).encode("utf-8")) <= 4096
    assert "very-secret-token" not in "\n".join(progress)


def test_tool_call_error() -> None:
    state = activity_reducer(
        make_state(),
        {"type": "tool_call", "name": "exec_docker", "input": {"args": ["ps"]}},
    )
    state = activity_reducer(
        state,
        {"type": "tool_error", "name": "exec_docker", "error": "exit 1"},
    )
    tool = state.items[0]
    assert tool.type == "tool"
    assert tool.status == "failed"
    assert state.active_tool_activity_id is None


def test_tool_cancellation() -> None:
    state = activity_reducer(
        make_state(),
        {"type": "tool_call", "name": "pull_image", "input": {"image": "nginx"}},
    )
    state = activity_reducer(state, {"type": "tool_cancelled"})
    tool = state.items[0]
    assert tool.type == "tool"
    assert tool.status == "cancelled"
    assert state.active_tool_activity_id is None


def test_falls_back_to_latest_running_tool_on_mismatched_result_name() -> None:
    state = activity_reducer(
        make_state(),
        {"type": "tool_call", "name": "exec_docker", "input": {"args": ["ps"]}},
    )
    state = activity_reducer(
        state,
        {"type": "tool_result", "name": "unknown_tool", "output": {}},
    )
    tool = state.items[0]
    assert tool.type == "tool"
    assert tool.status == "completed"


def test_ignores_progress_when_no_active_tool() -> None:
    state = activity_reducer(make_state(), {"type": "tool_progress", "msg": "orphan"})
    assert len(state.items) == 0


def test_assistant_text_delta_coalesces() -> None:
    state = activity_reducer(make_state(), {"type": "assistant_text", "delta": "Hello"})
    assert len(state.items) == 1
    item = state.items[0]
    assert item.type == "text"
    assert item.role == "assistant"
    assert item.text == "Hello"
    state = activity_reducer(state, {"type": "assistant_text", "delta": " world"})
    item = state.items[0]
    assert item.type == "text"
    assert item.role == "assistant"
    assert item.text == "Hello world"


def test_user_text() -> None:
    state = activity_reducer(make_state(), {"type": "user_text", "text": "deploy web"})
    item = state.items[0]
    assert item.type == "text"
    assert item.role == "user"
    assert item.text == "deploy web"


def test_error_event() -> None:
    state = activity_reducer(make_state(), {"type": "error", "error": RuntimeError("boom")})
    item = state.items[0]
    assert item.type == "text"
    assert item.role == "error"
    assert item.text == "boom"


def test_usage_event() -> None:
    state = activity_reducer(
        make_state(),
        {"type": "usage", "input_tokens": 10, "output_tokens": 20},
    )
    item = state.items[0]
    assert item.type == "usage"
    assert item.input_tokens == 10
    assert item.output_tokens == 20


def test_action_review_ready_resolved_and_toggle() -> None:
    state = activity_reducer(
        make_state(),
        {
            "type": "action_review_ready",
            "request_id": "review-1",
            "tool": "k8s.deploy",
            "title": "Deploy workload",
            "summary": "Create deployment/web",
            "artifacts": [
                {
                    "kind": "manifest",
                    "label": "Manifest",
                    "language": "yaml",
                    "content": "kind: Deployment",
                }
            ],
            "auto_generated_secrets": None,
            "config_files": None,
        },
    )
    review = state.items[0]
    assert review.type == "action_review"
    assert review.status == "pending"
    assert review.artifacts[0].label == "Manifest"
    state = activity_reducer(
        state,
        {"type": "action_review_toggle_artifacts", "request_id": "review-1"},
    )
    assert state.items[0].show_artifacts is True
    state = activity_reducer(
        state,
        {"type": "action_review_resolved", "request_id": "review-1", "status": "approved"},
    )
    assert state.items[0].status == "approved"


def test_action_review_ready_accepts_pydantic_secret_refs() -> None:
    from docker_agent.ui.activity import PlanConfigRef, PlanSecretRef

    state = activity_reducer(
        make_state(),
        {
            "type": "action_review_ready",
            "request_id": "review-2",
            "tool": "aws.deploy",
            "title": "Deploy service",
            "summary": "Create service/db",
            "artifacts": [],
            "auto_generated_secrets": [
                PlanSecretRef(service="db", keys=["POSTGRES_PASSWORD"]),
            ],
            "config_files": [
                PlanConfigRef(path="./app.js", content="console.log(1)", bytes=14),
            ],
        },
    )
    review = state.items[0]
    assert review.type == "action_review"
    assert len(review.auto_generated_secrets) == 1
    assert review.auto_generated_secrets[0].service == "db"
    assert review.auto_generated_secrets[0].keys == ["POSTGRES_PASSWORD"]
    assert len(review.config_files) == 1
    assert review.config_files[0].path == "./app.js"


def test_serialize_and_deserialize_action_review_activity() -> None:
    from docker_agent.ui.activity import (
        ActionReviewActivity,
        ActionReviewArtifactRef,
        deserialize_activity_items,
        serialize_activity_items,
    )

    items = [
        ActionReviewActivity(
            id="review-1",
            request_id="req-1",
            tool="k8s.deploy",
            title="Deploy workload",
            summary="Create deployment/web",
            artifacts=[
                ActionReviewArtifactRef(
                    kind="manifest",
                    label="Manifest",
                    content="kind: Deployment",
                    language="yaml",
                )
            ],
            status="approved",
            show_artifacts=True,
        )
    ]
    roundtrip = deserialize_activity_items(serialize_activity_items(items))
    assert len(roundtrip) == 1
    assert roundtrip[0].type == "action_review"
    assert roundtrip[0].request_id == "req-1"
    assert roundtrip[0].status == "approved"
    assert roundtrip[0].show_artifacts is True

def test_rollback_started_and_result() -> None:
    state = activity_reducer(
        make_state(),
        {
            "type": "rollback_started",
            "stack_name": "web",
            "reason": "apply_failed",
            "detail": "Deploy failed: exit 1. Starting rollback...",
        },
    )
    item = state.items[0]
    assert item.type == "rollback"
    assert item.stack_name == "web"
    assert item.phase == "started"
    assert item.detail == "Deploy failed: exit 1. Starting rollback..."
    state = activity_reducer(
        state,
        {
            "type": "rollback_result",
            "stack_name": "web",
            "ok": True,
            "restored": "previous",
        },
    )
    rollback = state.items[0]
    assert rollback.type == "rollback"
    assert rollback.phase == "completed"
    assert rollback.ok is True


def test_project_messages_pairs_tool_use_and_result() -> None:
    messages = [
        UserMessage(content="deploy"),
        AssistantMessage(
            content=[
                AssistantBlock.model_validate({"type": "text", "text": "OK"}),
                AssistantBlock.model_validate(
                    {
                        "type": "tool_use",
                        "id": "tu1",
                        "name": "plan_stack",
                        "input": {"stackName": "web"},
                    }
                ),
            ]
        ),
        ToolResultMessage(tool_use_id="tu1", content="planned", is_error=False),
    ]
    activities = project_messages_to_activities(messages)
    tool = next(item for item in activities if item.type == "tool")
    assert tool.name == "plan_stack"
    assert tool.status == "completed"
    assert len(tool.detail_lines) > 0


def test_project_messages_marks_tool_result_failed_when_is_error() -> None:
    messages = [
        AssistantMessage(
            content=[
                AssistantBlock.model_validate(
                    {
                        "type": "tool_use",
                        "id": "tu2",
                        "name": "exec_docker",
                        "input": {"args": ["ps"]},
                    }
                )
            ]
        ),
        ToolResultMessage(tool_use_id="tu2", content="failed", is_error=True),
    ]
    tool = next(item for item in project_messages_to_activities(messages) if item.type == "tool")
    assert tool.status == "failed"


def test_project_messages_marks_unsuccessful_output_as_failed() -> None:
    messages = [
        AssistantMessage(
            content=[
                AssistantBlock.model_validate(
                    {
                        "type": "tool_use",
                        "id": "tu3",
                        "name": "apply_stack",
                        "input": {"stackName": "web"},
                    }
                )
            ]
        ),
        ToolResultMessage(
            tool_use_id="tu3",
            content='{"ok":false,"exitCode":1}',
            is_error=False,
        ),
    ]
    tool = next(item for item in project_messages_to_activities(messages) if item.type == "tool")
    assert tool.status == "failed"


def test_project_messages_handles_orphaned_tool_result() -> None:
    messages = [
        ToolResultMessage(tool_use_id="tu_missing", content="result", is_error=False),
    ]
    activities = project_messages_to_activities(messages)
    assert any(item.type == "tool" for item in activities)


def test_project_messages_includes_user_and_assistant_text() -> None:
    messages = [
        UserMessage(content="hello"),
        AssistantMessage(
            content=[AssistantBlock.model_validate({"type": "text", "text": "hi"})]
        ),
    ]
    activities = project_messages_to_activities(messages)
    assert activities[0].type == "text"
    assert activities[0].role == "user"
    assert activities[0].text == "hello"
    assert activities[1].type == "text"
    assert activities[1].role == "assistant"
    assert activities[1].text == "hi"

