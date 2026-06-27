"""Parity tests for db_healthcheck — mirrors src/tools/shared/__tests__/dbHealthcheck.test.ts."""

from src.tools.shared.db_healthcheck import inject_db_healthchecks
from src.types.stack import HealthcheckSpec, ServiceSpec


def test_injects_healthcheck_to_custom_db_images_when_missing() -> None:
    services = {
        "db": ServiceSpec(image="postgres:16-alpine"),
        "web": ServiceSpec(image="nginx:1.27-alpine"),
    }
    result = inject_db_healthchecks(services)
    assert result["injected_count"] == 1
    assert services["db"].healthcheck is not None
    assert services["db"].healthcheck.test == [
        "CMD-SHELL",
        "pg_isready -U ${POSTGRES_USER:-postgres}",
    ]
    assert services["db"].healthcheck.start_period == "30s"
    assert services["web"].healthcheck is None


def test_does_not_overwrite_existing_healthcheck() -> None:
    services = {
        "db": ServiceSpec(
            image="mysql:8.4",
            healthcheck=HealthcheckSpec.model_validate(
                {
                    "test": ["CMD", "mysqladmin", "ping"],
                    "interval": "5s",
                    "timeout": "2s",
                    "retries": 3,
                }
            ),
        )
    }
    result = inject_db_healthchecks(services)
    assert result["injected_count"] == 0
    assert services["db"].healthcheck is not None
    assert services["db"].healthcheck.interval == "5s"
    assert services["db"].healthcheck.start_period is None


def test_upgrades_array_depends_on_for_db_dependencies() -> None:
    services = {
        "db": ServiceSpec(image="mysql:8.0"),
        "other": ServiceSpec(image="redis:7-alpine"),
        "web": ServiceSpec(image="wordpress:latest", depends_on=["db", "other"]),
    }
    result = inject_db_healthchecks(services)
    assert result["updated_deps_count"] == 1
    assert services["web"].depends_on == {
        "db": {"condition": "service_healthy"},
        "other": {"condition": "service_healthy"},
    }


def test_upgrades_array_depends_on_preserving_non_db_dependencies() -> None:
    services = {
        "db": ServiceSpec(image="postgres:16-alpine"),
        "app": ServiceSpec(image="node:20-alpine"),
        "web": ServiceSpec(image="nginx:alpine", depends_on=["db", "app"]),
    }
    result = inject_db_healthchecks(services)
    assert result["updated_deps_count"] == 1
    assert services["web"].depends_on == {
        "db": {"condition": "service_healthy"},
        "app": {"condition": "service_started"},
    }


def test_upgrades_record_depends_on_without_overwriting_completed_successfully() -> None:
    services = {
        "db": ServiceSpec(image="postgres:16-alpine"),
        "migration": ServiceSpec(image="postgres:16-alpine"),
        "web": ServiceSpec(
            image="nginx:alpine",
            depends_on={
                "db": {"condition": "service_started"},
                "migration": {"condition": "service_completed_successfully"},
            },
        ),
    }
    result = inject_db_healthchecks(services)
    assert result["updated_deps_count"] == 1
    assert services["web"].depends_on == {
        "db": {"condition": "service_healthy"},
        "migration": {"condition": "service_completed_successfully"},
    }