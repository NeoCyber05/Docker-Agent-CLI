"""Parity tests for infra_agent.types.permissions â€” mirrors src/types/permissions.ts:1-11."""

import pytest
from pydantic import ValidationError

from infra_agent.types.permissions import (
    AlwaysAllowInSession,
    Approve,
    Deny,
    PermissionRequest,
    PermissionResponse,
    SecretsInputValues,
    TypedConfirmValue,
)


def parse(obj: dict) -> PermissionResponse:
    """TypeAdapter â€” declared here so each test asserts the discriminated union parses."""
    from pydantic import TypeAdapter

    return TypeAdapter(PermissionResponse).validate_python(obj)


# --- variant instantiations ----------------------------------------------

def test_approve_round_trip() -> None:
    r = Approve()
    assert r.kind == "approve"
    assert parse({"kind": "approve"}).kind == "approve"


def test_deny_round_trip() -> None:
    r = Deny()
    assert r.kind == "deny"
    assert parse({"kind": "deny"}).kind == "deny"


def test_deny_can_carry_feedback() -> None:
    parsed = parse({"kind": "deny", "feedback": "doi port sang 8081"})
    assert isinstance(parsed, Deny)
    assert parsed.feedback == "doi port sang 8081"


def test_always_allow_in_session_round_trip() -> None:
    r = AlwaysAllowInSession()
    assert r.kind == "always_allow_in_session"
    assert parse({"kind": "always_allow_in_session"}).kind == "always_allow_in_session"


def test_typed_confirm_value_carries_value() -> None:
    r = TypedConfirmValue(value="DESTROY ALL")
    assert r.kind == "typed_confirm_value"
    assert r.value == "DESTROY ALL"
    parsed = parse({"kind": "typed_confirm_value", "value": "DESTROY ALL"})
    assert parsed.value == "DESTROY ALL"


def test_secrets_input_values_carries_values_map() -> None:
    payload = {"kind": "secrets_input_values", "values": {"POSTGRES_PASSWORD": "hunter2"}}
    parsed = parse(payload)
    assert isinstance(parsed, SecretsInputValues)
    assert parsed.values == {"POSTGRES_PASSWORD": "hunter2"}


# --- negative paths ------------------------------------------------------

def test_unknown_kind_rejected() -> None:
    with pytest.raises(ValidationError):
        parse({"kind": "bogus"})


def test_typed_confirm_value_requires_value_field() -> None:
    with pytest.raises(ValidationError):
        parse({"kind": "typed_confirm_value"})


def test_secrets_input_values_requires_values_field() -> None:
    with pytest.raises(ValidationError):
        parse({"kind": "secrets_input_values"})


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        parse({"kind": "approve", "sneaky": True})


# --- PermissionRequest ---------------------------------------------------

def test_permission_request_round_trip() -> None:
    req = PermissionRequest(tool="destroy_stack", input={"stackName": "db"})
    assert req.tool == "destroy_stack"
    assert req.input == {"stackName": "db"}


def test_permission_request_accepts_any_input_type() -> None:
    # input is `unknown` in TS â†’ Any in Python; object and primitive both fine
    PermissionRequest(tool="x", input=None)
    PermissionRequest(tool="x", input=42)
    PermissionRequest(tool="x", input=[1, 2])
