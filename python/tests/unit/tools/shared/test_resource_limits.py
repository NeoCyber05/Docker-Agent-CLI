"""Parity tests for resource_limits — mirrors src/tools/shared/__tests__/resourceLimits.test.ts."""

from docker_agent.tools.shared.resource_limits import (
    MAX_SERVICES_PER_STACK,
    check_resource_limits,
)
from docker_agent.types.stack import ServiceSpec


def _svc(image: str = "nginx:1.27-alpine") -> ServiceSpec:
    return ServiceSpec(image=image)


def test_passes_for_single_service_with_no_ports() -> None:
    assert check_resource_limits({"web": _svc()}) == []


def test_blocks_when_service_count_exceeds_max() -> None:
    services = {f"svc{i}": _svc() for i in range(MAX_SERVICES_PER_STACK + 1)}
    issues = check_resource_limits(services)
    assert len(issues) == 1
    assert issues[0].code == "too_many_services"
    assert str(MAX_SERVICES_PER_STACK + 1) in issues[0].message


def test_blocks_port_0_and_port_70000() -> None:
    issues = check_resource_limits(
        {
            "a": ServiceSpec(image="nginx:1.27-alpine", ports=["0:80"]),
            "b": ServiceSpec(image="nginx:1.27-alpine", ports=["70000:80"]),
        }
    )
    assert [issue.code for issue in issues] == ["invalid_port", "invalid_port"]
    assert issues[0].path == "services.a.ports[0]"


def test_warns_on_privileged_host_port_below_1024() -> None:
    issues = check_resource_limits(
        {"web": ServiceSpec(image="nginx:1.27-alpine", ports=["80:8080"])}
    )
    assert len(issues) == 1
    assert issues[0].code == "privileged_port"
    assert "80" in issues[0].message


def test_passes_for_non_privileged_port_8080() -> None:
    assert check_resource_limits(
        {"web": ServiceSpec(image="nginx:1.27-alpine", ports=["8080:80"])}
    ) == []


def test_ignores_container_only_ports() -> None:
    assert check_resource_limits(
        {"web": ServiceSpec(image="nginx:1.27-alpine", ports=["80"])}
    ) == []