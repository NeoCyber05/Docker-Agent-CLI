"""Parity tests for toolSchema adapter."""

from typing import Literal

from pydantic import BaseModel

from docker_agent.services.api.tool_schema import (
    to_gemini_function_declaration,
    to_json_schema,
    to_openai_function,
)
from docker_agent.services.api.types import ToolSchema


class SampleInput(BaseModel):
    stack_name: str
    count: int | None = None
    mode: Literal["fast", "slow"] = "fast"


def test_to_json_schema_object() -> None:
    schema = to_json_schema(SampleInput)
    assert schema["type"] == "object"
    assert "stack_name" in schema["properties"]
    assert schema["required"] == ["stack_name", "mode"]


def test_to_openai_function() -> None:
    tool = ToolSchema(name="sample", description="A sample tool", input_schema=SampleInput)
    fn = to_openai_function(tool)
    assert fn["type"] == "function"
    assert fn["function"]["name"] == "sample"


def test_to_gemini_strips_additional_properties() -> None:
    tool = ToolSchema(name="sample", description="A sample tool", input_schema=SampleInput)
    decl = to_gemini_function_declaration(tool)
    assert decl["name"] == "sample"
    assert "additionalProperties" not in decl["parameters"]
