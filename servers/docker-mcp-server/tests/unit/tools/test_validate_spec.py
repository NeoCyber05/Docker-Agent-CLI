"""Parity tests for validate_spec â€” mirrors src/tools/__tests__/validateSpec.test.ts."""

from __future__ import annotations

import pytest
from tool_helpers import drain_with_progress, make_ctx

from docker_mcp_server.services.docker.image_validator import ImageValidationResult
from docker_mcp_server.services.docker.types import ContainerSummary
from docker_mcp_server.tools.base import ToolContext
from docker_mcp_server.tools.validate_spec import (
    SpecIssue,
    ValidateSpecResult,
    validate_spec,
)
from tests.mocks.mock_docker_engine import MockDockerEngine


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


class FailingListContainersEngine(MockDockerEngine):
    async def list_containers(self, *, all: bool = False, filters=None):
        raise AssertionError("validate_spec should not inspect containers without host ports")


class DockerUnavailableEngine(MockDockerEngine):
    async def list_containers(self, *, all: bool = False, filters=None):
        raise OSError("connect ENOENT //./pipe/docker_engine")


def _with_draft_defaults(payload: dict) -> dict:
    return {
        "stackName": payload.get("stackName", "validate-test"),
        "intent": payload.get("intent", "validation test"),
        **payload,
    }


def _inspect_with_ports(
    container_id: str, container_port: str, host_port: str
) -> dict[str, object]:
    return {
        "Id": container_id,
        "Name": f"/{container_id}",
        "State": {"Status": "running"},
        "Config": {"Image": "nginx", "Env": [], "Labels": {}},
        "HostConfig": {"Binds": None, "PortBindings": {}},
        "NetworkSettings": {
            "Ports": {container_port: [{"HostIp": "0.0.0.0", "HostPort": host_port}]}
        },
        "RestartCount": 0,
    }


def _engine_with_published_port(
    *,
    container_id: str = "existing",
    project: str = "other",
    host_port: str = "8080",
    container_port: str = "80/tcp",
) -> MockDockerEngine:
    engine = MockDockerEngine()
    engine.containers.append(
        ContainerSummary.model_validate(
            {
                "Id": container_id,
                "Names": [f"/{container_id}"],
                "State": "running",
                "Labels": {"com.docker.compose.project": project},
            }
        ).model_dump(by_alias=True)
    )
    engine.inspect_by_id[container_id] = _inspect_with_ports(
        container_id, container_port, host_port
    )
    return engine


@pytest.mark.asyncio
async def test_returns_valid_for_simple_nginx_spec(tmp_project) -> None:
    _, result = await drain_with_progress(
        validate_spec.call(
            validate_spec.input_schema.model_validate(
                _with_draft_defaults(
                    {
                        "services": [
                            {
                                "name": "web",
                                "kind": "custom",
                                "image": "nginx:1.27-alpine",
                            }
                        ]
                    }
                )
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
                _with_draft_defaults(
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
                )
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
                _with_draft_defaults(
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
                )
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
                _with_draft_defaults(
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
                )
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
                _with_draft_defaults(
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
                )
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
                _with_draft_defaults(
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
                )
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
                _with_draft_defaults(
                    {
                        "services": [
                            {
                                "name": "db",
                                "kind": "custom",
                                "image": "postgres:does-not-exist",
                            }
                        ]
                    }
                )
            ),
            ctx,
        )
    )
    assert result.valid is False
    assert result.issues[0].code == "invalid_image"


@pytest.mark.asyncio
async def test_blocks_custom_node_service_without_app_source(tmp_project) -> None:
    _, result = await drain_with_progress(
        validate_spec.call(
            validate_spec.input_schema.model_validate(
                _with_draft_defaults(
                    {
                        "services": [
                            {
                                "name": "api",
                                "kind": "custom",
                                "image": "node:20-alpine",
                                "command": "node server.js",
                            }
                        ]
                    }
                )
            ),
            make_ctx(tmp_project),
        )
    )
    assert result.valid is False
    assert any(issue.code == "missing_app_source" for issue in result.issues)
    assert "server.js" in result.issues[0].message


@pytest.mark.asyncio
async def test_skips_runtime_port_check_when_no_host_ports(tmp_project) -> None:
    _, result = await drain_with_progress(
        validate_spec.call(
            validate_spec.input_schema.model_validate(
                _with_draft_defaults(
                    {
                        "services": [
                            {
                                "name": "web",
                                "kind": "custom",
                                "image": "nginx:1.27-alpine",
                            }
                        ]
                    }
                )
            ),
            make_ctx(tmp_project, docker_engine=FailingListContainersEngine()),
        )
    )
    assert result.valid is True


@pytest.mark.asyncio
async def test_reports_duplicate_draft_host_port(tmp_project) -> None:
    _, result = await drain_with_progress(
        validate_spec.call(
            validate_spec.input_schema.model_validate(
                _with_draft_defaults(
                    {
                        "services": [
                            {
                                "name": "web",
                                "kind": "custom",
                                "image": "nginx:1.27-alpine",
                                "exposure": "public",
                                "hostPort": 8080,
                                "containerPort": 80,
                            },
                            {
                                "name": "admin",
                                "kind": "custom",
                                "image": "nginx:1.27-alpine",
                                "exposure": "public",
                                "hostPort": 8080,
                                "containerPort": 8080,
                            },
                        ]
                    }
                )
            ),
            make_ctx(tmp_project),
        )
    )
    assert result.valid is False
    assert any(issue.code == "port_conflict" for issue in result.issues)
    assert "8080/tcp" in "\n".join(issue.message for issue in result.issues)


@pytest.mark.asyncio
async def test_reports_running_container_port_conflict(tmp_project) -> None:
    engine = _engine_with_published_port(host_port="8080")
    _, result = await drain_with_progress(
        validate_spec.call(
            validate_spec.input_schema.model_validate(
                _with_draft_defaults(
                    {
                        "stackName": "app",
                        "services": [
                            {
                                "name": "web",
                                "kind": "custom",
                                "image": "nginx:1.27-alpine",
                                "exposure": "public",
                                "hostPort": 8080,
                                "containerPort": 80,
                            }
                        ],
                    }
                )
            ),
            make_ctx(tmp_project, docker_engine=engine),
        )
    )
    assert result.valid is False
    assert any(issue.code == "port_conflict" for issue in result.issues)
    assert "existing" in "\n".join(issue.message for issue in result.issues)


@pytest.mark.asyncio
async def test_ignores_running_port_owned_by_same_stack(tmp_project) -> None:
    engine = _engine_with_published_port(project="app", host_port="8080")
    _, result = await drain_with_progress(
        validate_spec.call(
            validate_spec.input_schema.model_validate(
                _with_draft_defaults(
                    {
                        "stackName": "app",
                        "services": [
                            {
                                "name": "web",
                                "kind": "custom",
                                "image": "nginx:1.27-alpine",
                                "exposure": "public",
                                "hostPort": 8080,
                                "containerPort": 80,
                            }
                        ],
                    }
                )
            ),
            make_ctx(tmp_project, docker_engine=engine),
        )
    )
    assert result.valid is True


@pytest.mark.asyncio
async def test_reports_port_check_unavailable_when_docker_is_required(tmp_project) -> None:
    _, result = await drain_with_progress(
        validate_spec.call(
            validate_spec.input_schema.model_validate(
                _with_draft_defaults(
                    {
                        "services": [
                            {
                                "name": "web",
                                "kind": "custom",
                                "image": "nginx:1.27-alpine",
                                "exposure": "public",
                                "hostPort": 8080,
                                "containerPort": 80,
                            }
                        ],
                    }
                )
            ),
            make_ctx(tmp_project, docker_engine=DockerUnavailableEngine()),
        )
    )
    assert result.valid is False
    assert any(issue.code == "port_check_unavailable" for issue in result.issues)



