"""Parity tests for resolve_dependency — mirrors resolveDependency.test.ts."""

import pytest

from docker_agent.tools.resolve_dependency import ResolveDependencyInput, resolve_dependencies
from docker_agent.types.stack import ServiceSpec


def test_orders_dependencies_before_dependents() -> None:
    result = resolve_dependencies(
        {
            "api": ServiceSpec(image="example/api:1", depends_on=["db"]),
            "db": ServiceSpec(image="postgres:16-alpine"),
        }
    )
    assert result.valid is True
    assert result.order == ["db", "api"]
    assert result.missing == []
    assert result.cycles == []


def test_reports_missing_dependency_names() -> None:
    result = resolve_dependencies(
        {"api": ServiceSpec(image="example/api:1", depends_on=["db"])}
    )
    assert result.valid is False
    assert len(result.missing) == 1
    assert result.missing[0].service == "api"
    assert result.missing[0].dependency == "db"


def test_reports_dependency_cycle() -> None:
    result = resolve_dependencies(
        {
            "api": ServiceSpec(image="example/api:1", depends_on=["worker"]),
            "worker": ServiceSpec(image="example/worker:1", depends_on=["api"]),
        }
    )
    assert result.valid is False
    assert result.cycles == [["api", "worker", "api"]]


def test_supports_object_form_depends_on() -> None:
    result = resolve_dependencies(
        {
            "api": ServiceSpec(
                image="example/api:1",
                depends_on={"db": {"condition": "service_started"}},
            ),
            "db": ServiceSpec(image="postgres:16-alpine"),
        }
    )
    assert result.valid is True
    assert result.order == ["db", "api"]


# --- Tests for ResolveDependencyInput with custom networks/volumes ---


def test_resolve_dependency_input_accepts_custom_networks() -> None:
    """ResolveDependencyInput should accept a networks list without crashing."""
    data = {
        "stackName": "webapp",
        "services": [
            {
                "name": "web",
                "kind": "custom",
                "image": "nginx:1.27-alpine",
                "networks": ["frontend"],
            }
        ],
        "networks": [{"name": "frontend"}],
    }
    parsed = ResolveDependencyInput.model_validate(data)
    assert parsed.networks is not None
    assert len(parsed.networks) == 1
    assert parsed.networks[0].name == "frontend"


def test_resolve_dependency_input_accepts_custom_volumes() -> None:
    """ResolveDependencyInput should accept a volumes list without crashing."""
    data = {
        "stackName": "webapp",
        "services": [
            {
                "name": "web",
                "kind": "custom",
                "image": "nginx:1.27-alpine",
                "volumeMounts": [{"volume": "web-data", "target": "/data"}],
            }
        ],
        "volumes": [{"name": "web-data"}],
    }
    parsed = ResolveDependencyInput.model_validate(data)
    assert parsed.volumes is not None
    assert len(parsed.volumes) == 1
    assert parsed.volumes[0].name == "web-data"


def test_resolve_dependency_input_without_networks_is_still_valid() -> None:
    """When services don't use custom networks, networks field can be omitted."""
    data = {
        "services": [
            {
                "name": "api",
                "kind": "custom",
                "image": "example/api:1",
            }
        ],
    }
    parsed = ResolveDependencyInput.model_validate(data)
    assert parsed.networks is None
    assert parsed.volumes is None


def test_resolve_dependency_input_rejects_undeclared_network() -> None:
    """StackDraft validation should reject service referencing undeclared network.
    This should raise ValueError (not silently pass) so LLM knows to fix the input.
    """
    from pydantic import ValidationError

    data = {
        "stackName": "webapp",
        "services": [
            {
                "name": "web",
                "kind": "custom",
                "image": "nginx:1.27-alpine",
                "networks": ["frontend"],  # ← 'frontend' not in declared networks
            }
        ],
        # 'networks' field intentionally omitted → 'frontend' not declared
    }
    # ResolveDependencyInput accepts it (networks field is optional)
    parsed = ResolveDependencyInput.model_validate(data)
    assert parsed.networks is None

    # But when the tool tries to build StackDraft without 'frontend' declared,
    # it should fail with a clear Pydantic error — not a silent crash
    from docker_agent.tools.shared.spec_schemas import StackDraft

    with pytest.raises(ValidationError, match="not declared in top-level networks"):
        StackDraft.model_validate(
            {
                "stackName": "webapp",
                "intent": "validation only",
                "services": [
                    s.model_dump(by_alias=True, exclude_none=True)
                    for s in parsed.services
                ],
                # No networks passed → 'frontend' not declared
            }
        )
