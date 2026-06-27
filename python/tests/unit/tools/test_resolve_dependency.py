"""Parity tests for resolve_dependency — mirrors resolveDependency.test.ts."""

from docker_agent.tools.resolve_dependency import resolve_dependencies
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