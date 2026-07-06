"""Parity tests for spec_schemas â€” mirrors src/tools/shared/specSchemas.ts."""

import pytest
from pydantic import ValidationError

from docker_mcp_server.tools.shared.spec_schemas import (
    APPROVED_CATALOG_IDS,
    ConfigMount,
    HybridServiceIntent,
    StackDraft,
    parse_docker_mount_string,
)


def test_catalog_service_requires_approved_catalog_id() -> None:
    intent = HybridServiceIntent.model_validate(
        {"name": "db", "kind": "catalog", "catalogId": "postgresql:16"}
    )
    assert intent.catalog_id == "postgresql:16"


def test_catalog_service_rejects_unapproved_catalog_id() -> None:
    with pytest.raises(ValidationError, match="not allowed"):
        HybridServiceIntent.model_validate(
            {"name": "db", "kind": "catalog", "catalogId": "postgresql:99"}
        )


def test_catalog_service_rejects_image() -> None:
    with pytest.raises(ValidationError, match="image cannot be specified"):
        HybridServiceIntent.model_validate(
            {
                "name": "db",
                "kind": "catalog",
                "catalogId": "postgresql:16",
                "image": "postgres:16",
            }
        )


def test_custom_service_requires_image() -> None:
    with pytest.raises(ValidationError, match="image is required"):
        HybridServiceIntent.model_validate({"name": "web", "kind": "custom"})


def test_custom_service_rejects_catalog_id() -> None:
    with pytest.raises(ValidationError, match="catalogId cannot be specified"):
        HybridServiceIntent.model_validate(
            {
                "name": "web",
                "kind": "custom",
                "image": "nginx:1.27",
                "catalogId": "nginx:1.27",
            }
        )


def test_service_name_regex() -> None:
    with pytest.raises(ValidationError):
        HybridServiceIntent.model_validate(
            {"name": "Bad_Name", "kind": "custom", "image": "nginx"}
        )


def test_stack_draft_requires_at_least_one_service() -> None:
    with pytest.raises(ValidationError, match="at least one service"):
        StackDraft.model_validate(
            {"stackName": "demo", "intent": "test", "services": []}
        )


def test_stack_draft_requires_unique_service_names() -> None:
    with pytest.raises(ValidationError, match="unique"):
        StackDraft.model_validate(
            {
                "stackName": "demo",
                "intent": "test",
                "services": [
                    {"name": "web", "kind": "custom", "image": "nginx"},
                    {"name": "web", "kind": "custom", "image": "nginx"},
                ],
            }
        )


def test_approved_catalog_ids_match_ts_list() -> None:
    assert APPROVED_CATALOG_IDS == (
        "postgresql:16",
        "postgresql:15",
        "redis:7",
        "redis:6",
        "mysql:8.0",
        "mongodb:6.0",
        "nginx:1.27",
    )


def test_parse_docker_mount_string_basic() -> None:
    assert parse_docker_mount_string("./nginx.conf:/etc/nginx/nginx.conf") == {
        "hostPath": "./nginx.conf",
        "containerPath": "/etc/nginx/nginx.conf",
    }


def test_parse_docker_mount_string_strips_mode_suffix() -> None:
    assert parse_docker_mount_string("./nginx.conf:/etc/nginx/nginx.conf:ro") == {
        "hostPath": "./nginx.conf",
        "containerPath": "/etc/nginx/nginx.conf",
    }


def test_parse_docker_mount_string_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="config mount must be"):
        parse_docker_mount_string("invalid")


def test_coerce_config_mounts_from_docker_string() -> None:
    intent = HybridServiceIntent.model_validate(
        {
            "name": "web",
            "kind": "custom",
            "image": "nginx:1.27-alpine",
            "configMounts": ["./nginx.conf:/etc/nginx/nginx.conf"],
        }
    )
    assert intent.config_mounts == [
        ConfigMount(host_path="./nginx.conf", container_path="/etc/nginx/nginx.conf")
    ]


def test_coerce_config_mounts_from_object() -> None:
    intent = HybridServiceIntent.model_validate(
        {
            "name": "web",
            "kind": "custom",
            "image": "nginx:1.27-alpine",
            "configMounts": [
                {
                    "hostPath": "./nginx.conf",
                    "containerPath": "/etc/nginx/nginx.conf",
                }
            ],
        }
    )
    assert intent.config_mounts == [
        ConfigMount(host_path="./nginx.conf", container_path="/etc/nginx/nginx.conf")
    ]


def test_stack_draft_rejects_undeclared_service_network() -> None:
    with pytest.raises(ValidationError, match="not declared in top-level networks"):
        StackDraft.model_validate(
            {
                "stackName": "demo",
                "intent": "test",
                "services": [
                    {
                        "name": "web",
                        "kind": "custom",
                        "image": "nginx",
                        "networks": ["backend"],
                    }
                ],
            }
        )


def test_stack_draft_rejects_undeclared_volume_mount() -> None:
    with pytest.raises(ValidationError, match="not declared in top-level volumes"):
        StackDraft.model_validate(
            {
                "stackName": "demo",
                "intent": "test",
                "services": [
                    {
                        "name": "web",
                        "kind": "custom",
                        "image": "nginx",
                        "volumeMounts": [{"volume": "data", "target": "/data"}],
                    }
                ],
            }
        )


def test_stack_draft_accepts_declared_networks_and_volumes() -> None:
    draft = StackDraft.model_validate(
        {
            "stackName": "demo",
            "intent": "test",
            "networks": [{"name": "backend", "internal": True}],
            "volumes": [{"name": "pgdata", "driver": "local"}],
            "services": [
                {
                    "name": "db",
                    "kind": "catalog",
                    "catalogId": "postgresql:16",
                    "networks": ["backend", "default"],
                    "volumeMounts": [{"volume": "pgdata", "target": "/var/lib/postgresql/data"}],
                }
            ],
        }
    )
    assert draft.networks is not None
    assert draft.networks[0].internal is True
    assert draft.volumes is not None
    assert draft.volumes[0].driver == "local"


def test_stack_draft_rejects_reserved_default_network_name() -> None:
    with pytest.raises(ValidationError, match="reserved"):
        StackDraft.model_validate(
            {
                "stackName": "demo",
                "intent": "test",
                "networks": [{"name": "default"}],
                "services": [
                    {"name": "web", "kind": "custom", "image": "nginx"},
                ],
            }
        )


