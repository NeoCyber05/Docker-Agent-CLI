"""Parity tests for network_guard — mirrors src/tools/shared/__tests__/networkGuard.test.ts."""

from src.tools.shared.network_guard import check_network_references
from src.types.stack import ServiceSpec


def _svc(networks: list[str]) -> ServiceSpec:
    return ServiceSpec(image="nginx:1.27-alpine", networks=networks)


def test_passes_when_all_service_networks_are_declared() -> None:
    assert check_network_references({"web": _svc(["frontend"])}, {"frontend": {}}) == []


def test_blocks_undeclared_network_reference() -> None:
    issues = check_network_references({"web": _svc(["ghost"])}, {"frontend": {}})
    assert len(issues) == 1
    assert issues[0].code == "undeclared_network"
    assert issues[0].network == "ghost"


def test_passes_when_no_top_level_networks_and_service_has_no_networks() -> None:
    assert check_network_references({"web": _svc([])}, None) == []


def test_blocks_multiple_undeclared_networks() -> None:
    issues = check_network_references(
        {"web": _svc(["frontend", "backend"])}, {"frontend": {}}
    )
    assert len(issues) == 1
    assert issues[0].network == "backend"


def test_passes_when_networks_undefined_but_services_use_default() -> None:
    assert check_network_references(
        {"web": ServiceSpec(image="nginx:1.27-alpine")}, None
    ) == []