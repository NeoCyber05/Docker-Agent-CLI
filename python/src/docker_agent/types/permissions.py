"""Permission user-response discriminated union.

Parity: ``src/types/permissions.ts:1-11``.

Five variants keyed by ``kind``. The Python field names are snake_case but
aliased to the TS camelCase names via pydantic ``Field(alias=...)`` so we can
ingest provider/UI payloads that look identical to the TS ones.

``PermissionRequest`` is the engine's outbound request shape (the ``PermissionResponse``
is the UI's answer).
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

# All models forbid extra fields and accept inputs by either the python_name
# or the camelCase alias. populate_by_name stays True so internal pythonic
# construction still works.
_MODEL_CONFIG = ConfigDict(extra="forbid", populate_by_name=True)


class Approve(BaseModel):
    """User approved the request as a one-off."""

    model_config = _MODEL_CONFIG
    kind: Literal["approve"] = "approve"


class Deny(BaseModel):
    """User denied the request (one-off)."""

    model_config = _MODEL_CONFIG
    kind: Literal["deny"] = "deny"


class AlwaysAllowInSession(BaseModel):
    """User approved and asked to remember for the rest of the session."""

    model_config = _MODEL_CONFIG
    kind: Literal["always_allow_in_session"] = "always_allow_in_session"


class TypedConfirmValue(BaseModel):
    """User typed the required confirmation phrase (e.g. "DESTROY ALL")."""

    model_config = _MODEL_CONFIG
    kind: Literal["typed_confirm_value"] = "typed_confirm_value"
    value: str


class SecretsInputValues(BaseModel):
    """User filled in required secret env values for a service."""

    model_config = _MODEL_CONFIG
    kind: Literal["secrets_input_values"] = "secrets_input_values"
    values: dict[str, str]


# Discriminated union — pydantic picks the right variant based on ``kind``.
PermissionResponse = Annotated[
    Approve | Deny | AlwaysAllowInSession | TypedConfirmValue | SecretsInputValues,
    Field(discriminator="kind"),
]


class PermissionRequest(BaseModel):
    """Engine → UI request for permission. ``input`` mirrors TS ``unknown``."""

    model_config = _MODEL_CONFIG
    tool: str
    input: Any


# Expose a TypeAdapter at module scope so callers don't have to rebuild it.
PermissionResponseAdapter: TypeAdapter[PermissionResponse] = TypeAdapter(PermissionResponse)


__all__ = [
    "AlwaysAllowInSession",
    "Approve",
    "Deny",
    "PermissionRequest",
    "PermissionResponse",
    "PermissionResponseAdapter",
    "SecretsInputValues",
    "TypedConfirmValue",
]