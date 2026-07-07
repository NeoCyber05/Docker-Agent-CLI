"""Parity tests for infra_agent.types.message â€” mirrors src/types/message.ts:1-22."""

import pytest
from pydantic import TypeAdapter, ValidationError

from infra_agent.types.message import (
    AssistantBlock,
    AssistantMessage,
    Message,
    ToolResultMessage,
    UserMessage,
)

message_adapter = TypeAdapter(Message)


# --- AssistantBlock dual variant -----------------------------------------

def test_assistant_block_text_variant() -> None:
    b = AssistantBlock.model_validate({"type": "text", "text": "hi"})
    assert b.type == "text"
    assert b.text == "hi"


def test_assistant_block_tool_use_variant_carries_input() -> None:
    b = AssistantBlock.model_validate(
        {"type": "tool_use", "id": "t1", "name": "list_stacks", "input": {}}
    )
    assert b.type == "tool_use"
    assert b.id == "t1"
    assert b.name == "list_stacks"
    assert b.input == {}


def test_assistant_block_tool_use_input_can_be_complex() -> None:
    b = AssistantBlock.model_validate({
        "type": "tool_use",
        "id": "t2",
        "name": "plan_stack",
        "input": {"stackName": "db", "services": []},
    })
    assert b.input == {"stackName": "db", "services": []}


def test_assistant_block_unknown_type_rejected() -> None:
    with pytest.raises(ValidationError):
        AssistantBlock.model_validate({"type": "image", "text": "x"})


# --- Message union -------------------------------------------------------

def test_user_message_parses() -> None:
    m = message_adapter.validate_python({"role": "user", "content": "hello"})
    assert isinstance(m, UserMessage)
    assert m.content == "hello"


def test_assistant_message_parses_with_text_block() -> None:
    m = message_adapter.validate_python(
        {"role": "assistant", "content": [{"type": "text", "text": "ack"}]}
    )
    assert isinstance(m, AssistantMessage)
    assert m.content[0].text == "ack"


def test_assistant_message_parses_with_tool_use_block() -> None:
    m = message_adapter.validate_python(
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "thinking"},
                {"type": "tool_use", "id": "t1", "name": "list_stacks", "input": {}},
            ],
        }
    )
    assert isinstance(m, AssistantMessage)
    assert len(m.content) == 2
    assert m.content[1].name == "list_stacks"


def test_tool_result_message_parses() -> None:
    m = message_adapter.validate_python(
        {"role": "tool", "toolUseId": "t1", "content": "[]", "isError": False}
    )
    assert isinstance(m, ToolResultMessage)
    assert m.tool_use_id == "t1"
    assert m.is_error is False


def test_tool_result_message_accepts_python_snake_case_alias() -> None:
    # Python callers may also construct with snake_case â€” pydantic must accept both
    m = ToolResultMessage(role="tool", tool_use_id="t1", content="[]", is_error=False)
    assert m.tool_use_id == "t1"
    # but when dumped by alias (json mode), camelCase must come back out
    dumped = m.model_dump(by_alias=True)
    assert dumped == {"role": "tool", "toolUseId": "t1", "content": "[]", "isError": False}


def test_message_unknown_role_rejected() -> None:
    with pytest.raises(ValidationError):
        message_adapter.validate_python({"role": "system", "content": "x"})


def test_assistant_message_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        message_adapter.validate_python(
            {"role": "assistant", "content": [], "extra": True}
        )


# --- round-trip serialization --------------------------------------------

def test_full_transcript_round_trip() -> None:
    payload = [
        {"role": "user", "content": "list stacks"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Sure"},
                {"type": "tool_use", "id": "t1", "name": "list_stacks", "input": {}},
            ],
        },
        {"role": "tool", "toolUseId": "t1", "content": "[]", "isError": False},
        {"role": "assistant", "content": [{"type": "text", "text": "none"}]},
    ]
    parsed = [message_adapter.validate_python(p) for p in payload]
    re_dumped = [m.model_dump(by_alias=True) for m in parsed]
    assert re_dumped == payload
