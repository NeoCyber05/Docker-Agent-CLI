"""LLM transcript message union.
Two axes of discrimination:
1. ``Message.role`` ∈ {"user","assistant","tool"} — three distinct model shapes.
2. ``AssistantBlock.type`` ∈ {"text","tool_use"} — nested union inside
   ``AssistantMessage.content``.

Field aliases match the TS camelCase names exactly so payloads produced by the
TS backend (e.g. Provider message-mapping logic) round-trip through pydantic
without manual key renaming.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

_MODEL_CONFIG = ConfigDict(extra="forbid", populate_by_name=True)


# --- AssistantBlock (inner discriminated union) -------------------------


class _AssistantText(BaseModel):
    """``{type:"text", text:string}`` block — plaintext assistant output."""

    model_config = _MODEL_CONFIG
    type: Literal["text"] = "text"
    text: str


class _AssistantToolUse(BaseModel):
    """``{type:"tool_use", id, name, input}`` block — assistant calling a tool."""

    model_config = _MODEL_CONFIG
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: Any


AssistantBlockUnion = Annotated[
    _AssistantText | _AssistantToolUse,
    Field(discriminator="type"),
]

_AssistantBlockAdapter: TypeAdapter[Any] = TypeAdapter(AssistantBlockUnion)


class AssistantBlock:
    """Validator-front for the discriminated ``AssistantBlockUnion``.

    Mirrors the pydantic v1-esque ``model_validate`` / ``model_dump`` API so
    call sites read like zod's ``schema.parse(...)``.
    """

    @staticmethod
    def model_validate(obj: dict[str, Any]) -> Any:
        return _AssistantBlockAdapter.validate_python(obj)

    @staticmethod
    def model_dump(value: Any, *, by_alias: bool = False) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(by_alias=by_alias)
        return value


# --- Top-level Message union --------------------------------------------


class UserMessage(BaseModel):
    """``{role:"user", content:string}``."""

    model_config = _MODEL_CONFIG
    role: Literal["user"] = "user"
    content: str


class AssistantMessage(BaseModel):
    """``{role:"assistant", content: AssistantBlock[]}``."""

    model_config = _MODEL_CONFIG
    role: Literal["assistant"] = "assistant"
    content: list[AssistantBlockUnion]


class ToolResultMessage(BaseModel):
    """``{role:"tool", toolUseId, content, isError}``."""

    model_config = _MODEL_CONFIG
    role: Literal["tool"] = "tool"
    tool_use_id: str = Field(alias="toolUseId")
    content: str
    is_error: bool = Field(alias="isError")


Message = Annotated[
    UserMessage | AssistantMessage | ToolResultMessage,
    Field(discriminator="role"),
]


__all__ = [
    "AssistantBlock",
    "AssistantMessage",
    "Message",
    "ToolResultMessage",
    "UserMessage",
]