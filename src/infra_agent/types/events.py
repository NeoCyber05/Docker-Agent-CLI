"""LoopEvent discriminated union."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_MODEL_CONFIG = ConfigDict(extra="forbid", populate_by_name=True)
_ERROR_CONFIG = ConfigDict(
    extra="forbid", populate_by_name=True, arbitrary_types_allowed=True
)


class ActionReviewArtifact(BaseModel):
    model_config = _MODEL_CONFIG
    kind: str
    label: str
    content: Any
    language: str | None = None


class IterationStart(BaseModel):
    model_config = _MODEL_CONFIG
    type: Literal["iteration_start"] = "iteration_start"
    n: int


class AssistantText(BaseModel):
    model_config = _MODEL_CONFIG
    type: Literal["assistant_text"] = "assistant_text"
    delta: str


class ToolCall(BaseModel):
    model_config = _MODEL_CONFIG
    type: Literal["tool_call"] = "tool_call"
    name: str
    input: Any


class ToolProgress(BaseModel):
    model_config = _MODEL_CONFIG
    type: Literal["tool_progress"] = "tool_progress"
    msg: str


class ToolResult(BaseModel):
    model_config = _MODEL_CONFIG
    type: Literal["tool_result"] = "tool_result"
    name: str
    output: Any


class PermissionRequest(BaseModel):
    model_config = _MODEL_CONFIG
    type: Literal["permission_request"] = "permission_request"
    id: str
    tool: str
    input: Any


class ActionReview(BaseModel):
    model_config = _MODEL_CONFIG
    type: Literal["action_review"] = "action_review"
    id: str
    pending_action_id: str = Field(alias="pendingActionId")
    tool: str
    title: str
    summary: str
    artifacts: list[ActionReviewArtifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    secrets: list[dict[str, Any]] = Field(default_factory=list)
    config_files: list[dict[str, Any]] = Field(default_factory=list, alias="configFiles")


class TypedConfirmRequest(BaseModel):
    model_config = _MODEL_CONFIG
    type: Literal["typed_confirm_request"] = "typed_confirm_request"
    id: str
    phrase: str
    reason: str


class SecretsInputRequest(BaseModel):
    model_config = _MODEL_CONFIG
    type: Literal["secrets_input_request"] = "secrets_input_request"
    id: str
    service: str
    keys: list[str]
    reason: str


class Usage(BaseModel):
    model_config = _MODEL_CONFIG
    type: Literal["usage"] = "usage"
    input_tokens: int = Field(alias="inputTokens")
    output_tokens: int = Field(alias="outputTokens")


class Error(BaseModel):
    model_config = _ERROR_CONFIG
    type: Literal["error"] = "error"
    error: BaseException


class RollbackStarted(BaseModel):
    model_config = _MODEL_CONFIG
    type: Literal["rollback_started"] = "rollback_started"
    stack_name: str = Field(alias="stackName")
    reason: Literal["apply_failed", "unhealthy"] | str
    detail: str
    running_services: list[str] | None = Field(default=None, alias="runningServices")


class RollbackResult(BaseModel):
    model_config = _MODEL_CONFIG
    type: Literal["rollback_result"] = "rollback_result"
    stack_name: str = Field(alias="stackName")
    ok: bool
    restored: Literal["previous", "removed", "none"] | str
    detail: str | None = None


_LoopEventUnion = (
    IterationStart
    | AssistantText
    | ToolCall
    | ToolProgress
    | ToolResult
    | PermissionRequest
    | ActionReview
    | TypedConfirmRequest
    | SecretsInputRequest
    | Usage
    | Error
    | RollbackStarted
    | RollbackResult
)

LoopEvent = Annotated[_LoopEventUnion, Field(discriminator="type")]


from infra_agent.types.permissions import (  # noqa: E402
    PermissionResponse,
)

__all__ = [
    "ActionReview",
    "ActionReviewArtifact",
    "AssistantText",
    "Error",
    "IterationStart",
    "LoopEvent",
    "PermissionRequest",
    "PermissionResponse",
    "RollbackResult",
    "RollbackStarted",
    "SecretsInputRequest",
    "ToolCall",
    "ToolProgress",
    "ToolResult",
    "TypedConfirmRequest",
    "Usage",
]
