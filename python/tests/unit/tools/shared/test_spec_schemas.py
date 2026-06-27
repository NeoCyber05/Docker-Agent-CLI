"""Parity tests for spec_schemas — mirrors src/tools/shared/specSchemas.ts."""

import pytest
from pydantic import ValidationError

from docker_agent.tools.shared.spec_schemas import (
    APPROVED_CATALOG_IDS,
    HybridServiceIntent,
    StackDraft,
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