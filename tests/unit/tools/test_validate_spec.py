"""Parity tests for validate_spec — mirrors src/tools/__tests__/validateSpec.test.ts."""

from __future__ import annotations

import pytest

from docker_agent.services.docker.image_validator import ImageValidationResult
from docker_agent.tools.base import ToolContext
from docker_agent.tools.validate_spec import (
    SpecIssue,
    ValidateSpecResult,
    validate_spec,
)
from tests.unit.tools.conftest import drain_with_progress, make_ctx


class InvalidImageValidator:
    async def validate_images(
        self, images: list[str], *, signal: object | None = None
    ) -> list[ImageValidationResult]:
        return [
            ImageValidationResult(
                image=image,
                status="invalid",
                source="registry",
                error="manifest not found",
                suggestion="postgres:16-alpine",
            )
            for image in images
        ]


@pytest.mark.asyncio
async def test_returns_valid_for_simple_nginx_spec(tmp_project) -> None:
    _, result = await drain_with_progress(
        validate_spec.call(
            validate_spec.input_schema.model_validate(
                {
                    "services": [
                        {
                            "name": "web",
                            "kind": "custom",
                            "image": "nginx:1.27-alpine",
                        }
                    ]
                }
            ),
            make_ctx(tmp_project),
        )
    )
    assert result == ValidateSpecResult(valid=True, issues=[], warnings=[])


@pytest.mark.asyncio
async def test_returns_structured_observation_for_missing_config_content(
    tmp_project,
) -> None:
    _, result = await drain_with_progress(
        validate_spec.call(
            validate_spec.input_schema.model_validate(
                {
                    "services": [
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
                    ]
                }
            ),
            make_ctx(tmp_project),
        )
    )
    assert result == ValidateSpecResult(
        valid=False,
        issues=[
            SpecIssue(
                code="missing_config_file",
                path="services.web.volumes",
                message=(
                    "Missing content for bind-mounted config file './nginx.conf'."
                ),
            )
        ],
        warnings=[],
    )


@pytest.mark.asyncio
async def test_accepts_docker_string_config_mount(tmp_project) -> None:
    """LLM may send configMounts as Docker volume strings; must not crash."""
    _, result = await drain_with_progress(
        validate_spec.call(
            validate_spec.input_schema.model_validate(
                {
                    "services": [
                        {
                            "name": "web",
                            "kind": "custom",
                            "image": "nginx:1.27-alpine",
                            "configMounts": [
                                "./nginx.conf:/etc/nginx/nginx.conf",
                            ],
                        }
                    ]
                }
            ),
            make_ctx(tmp_project),
        )
    )
    assert result == ValidateSpecResult(
        valid=False,
        issues=[
            SpecIssue(
                code="missing_config_file",
                path="services.web.volumes",
                message=(
                    "Missing content for bind-mounted config file './nginx.conf'."
                ),
            )
        ],
        warnings=[],
    )


@pytest.mark.asyncio
async def test_reports_unsafe_config_path(tmp_project) -> None:
    _, result = await drain_with_progress(
        validate_spec.call(
            validate_spec.input_schema.model_validate(
                {
                    "services": [
                        {
                            "name": "web",
                            "kind": "custom",
                            "image": "nginx:1.27-alpine",
                        }
                    ],
                    "configFiles": {"../escape.conf": "content"},
                }
            ),
            make_ctx(tmp_project),
        )
    )
    assert result.valid is False
    assert result.issues[0].code == "invalid_config_path"


@pytest.mark.asyncio
async def test_accepts_declared_top_level_networks(tmp_project) -> None:
    _, result = await drain_with_progress(
        validate_spec.call(
            validate_spec.input_schema.model_validate(
                {
                    "services": [
                        {
                            "name": "web",
                            "kind": "catalog",
                            "catalogId": "nginx:1.27",
                            "exposure": "public",
                            "networks": ["frontend"],
                        },
                        {
                            "name": "api",
                            "kind": "custom",
                            "image": "node:20-alpine",
                            "networks": ["frontend", "backend"],
                            "depends_on": ["db"],
                        },
                        {
                            "name": "db",
                            "kind": "catalog",
                            "catalogId": "postgresql:16",
                            "networks": ["backend"],
                        },
                    ],
                    "networks": [
                        {"name": "frontend"},
                        {"name": "backend", "internal": True},
                    ],
                }
            ),
            make_ctx(tmp_project),
        )
    )
    assert result.valid is True


@pytest.mark.asyncio
async def test_rejects_undeclared_service_network(tmp_project) -> None:
    _, result = await drain_with_progress(
        validate_spec.call(
            validate_spec.input_schema.model_validate(
                {
                    "services": [
                        {
                            "name": "web",
                            "kind": "custom",
                            "image": "nginx:1.27-alpine",
                            "networks": ["frontend"],
                        }
                    ]
                }
            ),
            make_ctx(tmp_project),
        )
    )
    assert result.valid is False
    assert result.issues[0].code == "invalid_spec"
    assert "frontend" in result.issues[0].message


@pytest.mark.asyncio
async def test_reports_invalid_image(tmp_project) -> None:
    base_ctx = make_ctx(tmp_project)
    ctx = ToolContext(
        cwd=base_ctx.cwd,
        state_store=base_ctx.state_store,
        docker_engine=base_ctx.docker_engine,
        compose_runner=base_ctx.compose_runner,
        abort_signal=base_ctx.abort_signal,
        image_validator=InvalidImageValidator(),  # type: ignore[arg-type]
    )
    _, result = await drain_with_progress(
        validate_spec.call(
            validate_spec.input_schema.model_validate(
                {
                    "services": [
                        {
                            "name": "db",
                            "kind": "custom",
                            "image": "postgres:does-not-exist",
                        }
                    ]
                }
            ),
            ctx,
        )
    )
    assert result.valid is False
    assert result.issues[0].code == "invalid_image"