"""Parity tests for plan_stack — mirrors src/tools/__tests__/planStack.test.ts."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from docker_agent.services.docker.image_validator import ImageValidationResult
from docker_agent.tools.plan_stack import plan_stack
from docker_agent.tools.shared.spec_schemas import StackDraft
from tests.mocks.mock_docker_engine import MockDockerEngine
from tests.unit.tools.conftest import drain_with_progress, make_ctx


class InvalidImageValidator:
    def __init__(self, image: str) -> None:
        self._image = image

    async def validate_image(
        self, image: str, *, signal: object | None = None
    ) -> ImageValidationResult:
        del signal
        return ImageValidationResult(
            image=image,
            status="invalid",
            source="registry",
            error="manifest not found",
            suggestion="postgres:16-alpine",
        )

    async def validate_images(
        self, images: list[str], *, signal: object | None = None
    ) -> list[ImageValidationResult]:
        del signal
        return [await self.validate_image(image) for image in images]


def _ctx(tmp_project: Path, *, engine: MockDockerEngine | None = None):
    return make_ctx(tmp_project, docker_engine=engine or MockDockerEngine())


async def _plan(input_data: dict, ctx) -> object:
    _, result = await drain_with_progress(
        plan_stack.call(StackDraft.model_validate(input_data), ctx)
    )
    return result


@pytest.mark.asyncio
async def test_simple_nginx_compose_yaml_and_empty_diff(tmp_project: Path) -> None:
    ctx = _ctx(tmp_project)
    result = await _plan(
        {
            "stackName": "test",
            "intent": "nginx",
            "services": [
                {
                    "name": "nginx",
                    "kind": "custom",
                    "image": "nginx:1.27-alpine",
                    "exposure": "public",
                    "hostPort": 8080,
                    "containerPort": 80,
                }
            ],
        },
        ctx,
    )

    assert result.blocked is False
    assert "nginx:1.27-alpine" in result.compose_yaml
    assert "8080:80" in result.compose_yaml


@pytest.mark.asyncio
async def test_inline_secret_auto_migrated_to_generated_env_file(
    tmp_project: Path,
) -> None:
    ctx = _ctx(tmp_project)
    result = await _plan(
        {
            "stackName": "s",
            "intent": "x",
            "services": [
                {
                    "name": "api",
                    "kind": "custom",
                    "image": "node:20",
                    "environment": {"NODE_ENV": "prod", "API_KEY": "leakvalue"},
                }
            ],
        },
        ctx,
    )

    assert result.blocked is False
    assert "leakvalue" not in result.compose_yaml
    assert any(
        item.service == "api" and item.keys == ["API_KEY"]
        for item in result.auto_generated_secrets
    )
    parsed = yaml.safe_load(result.compose_yaml)
    assert parsed["x-docker-agent"]["envFileSources"] == {
        "api": {
            "generated": True,
            "path": "./.docker-agent/secrets/s-api.env",
            "addedKeys": ["API_KEY"],
        }
    }
    generated_path = tmp_project / ".docker-agent" / "secrets" / "s-api.env"
    assert generated_path.exists()
    assert "API_KEY=leakvalue" in generated_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_postgres_without_env_file_auto_generates_postgres_password(
    tmp_project: Path,
) -> None:
    ctx = _ctx(tmp_project)
    result = await _plan(
        {
            "stackName": "p",
            "intent": "postgres",
            "services": [
                {
                    "name": "db",
                    "kind": "catalog",
                    "catalogId": "postgresql:16",
                }
            ],
        },
        ctx,
    )

    assert result.blocked is False
    assert any(
        item.service == "db" and item.keys == ["POSTGRES_PASSWORD"]
        for item in result.auto_generated_secrets
    )
    env_file = tmp_project / ".docker-agent" / "secrets" / "p-db.env"
    assert re.search(r"POSTGRES_PASSWORD=.{20,}", env_file.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_custom_image_without_required_secret_policy_is_not_blocked(
    tmp_project: Path,
) -> None:
    ctx = _ctx(tmp_project)
    result = await _plan(
        {
            "stackName": "b",
            "intent": "billing",
            "services": [
                {
                    "name": "worker",
                    "kind": "custom",
                    "image": "mycorp/billing:1.0",
                }
            ],
        },
        ctx,
    )

    assert result.blocked is False


@pytest.mark.asyncio
async def test_scale_field_stored_in_yaml(tmp_project: Path) -> None:
    ctx = _ctx(tmp_project)
    result = await _plan(
        {
            "stackName": "scaled",
            "intent": "x",
            "services": [
                {
                    "name": "api",
                    "kind": "custom",
                    "image": "node:20",
                    "scale": 2,
                }
            ],
        },
        ctx,
    )

    assert result.blocked is False
    assert re.search(r"api:\s*[\s\S]*scale:\s*2", result.compose_yaml)
    assert result.scale_overrides == {"api": 2}


@pytest.mark.asyncio
async def test_rejects_invalid_image_tags_before_writing_generated_secrets(
    tmp_project: Path,
) -> None:
    ctx = _ctx(tmp_project)
    ctx = replace(ctx, image_validator=InvalidImageValidator("postgres:99-alpine"))
    result = await _plan(
        {
            "stackName": "bad",
            "intent": "postgres",
            "services": [
                {
                    "name": "db",
                    "kind": "custom",
                    "image": "postgres:99-alpine",
                }
            ],
        },
        ctx,
    )

    assert result.blocked is True
    assert result.reason == "invalid_spec"
    assert not (tmp_project / ".docker-agent" / "secrets" / "bad-db.env").exists()


@pytest.mark.asyncio
async def test_stages_provided_config_file_content(tmp_project: Path) -> None:
    ctx = _ctx(tmp_project)
    result = await _plan(
        {
            "stackName": "web",
            "intent": "nginx proxy",
            "services": [
                {
                    "name": "nginx",
                    "kind": "custom",
                    "image": "nginx:1.27",
                    "configMounts": [
                        {
                            "hostPath": "./nginx.conf",
                            "containerPath": "/etc/nginx/nginx.conf",
                        }
                    ],
                }
            ],
            "configFiles": {"./nginx.conf": "events {}\n"},
        },
        ctx,
    )

    assert result.blocked is False
    assert len(result.config_files) == 1
    assert result.config_files[0].path == "nginx.conf"
    assert result.config_files[0].content == "events {}\n"
    assert result.config_files[0].bytes == 10
    assert not (tmp_project / "nginx.conf").exists()


@pytest.mark.asyncio
async def test_blocks_file_bind_with_no_content_and_no_host_file(
    tmp_project: Path,
) -> None:
    ctx = _ctx(tmp_project)
    result = await _plan(
        {
            "stackName": "web",
            "intent": "nginx proxy",
            "services": [
                {
                    "name": "nginx",
                    "kind": "custom",
                    "image": "nginx:1.27",
                    "configMounts": [
                        {
                            "hostPath": "./nginx.conf",
                            "containerPath": "/etc/nginx/nginx.conf",
                        }
                    ],
                }
            ],
        },
        ctx,
    )

    assert result.blocked is True
    assert result.reason == "invalid_spec"


@pytest.mark.asyncio
async def test_blocks_on_unsafe_config_file_path(tmp_project: Path) -> None:
    ctx = _ctx(tmp_project)
    result = await _plan(
        {
            "stackName": "web",
            "intent": "x",
            "services": [
                {
                    "name": "nginx",
                    "kind": "custom",
                    "image": "nginx:1.27",
                    "configMounts": [
                        {
                            "hostPath": "./nginx.conf",
                            "containerPath": "/etc/nginx/nginx.conf",
                        }
                    ],
                }
            ],
            "configFiles": {"../evil.conf": "x"},
        },
        ctx,
    )

    assert result.blocked is True
    assert result.reason == "invalid_spec"


@pytest.mark.asyncio
async def test_blocks_missing_dependency_before_writing_secrets(
    tmp_project: Path,
) -> None:
    ctx = _ctx(tmp_project)
    result = await _plan(
        {
            "stackName": "app",
            "intent": "api",
            "services": [
                {
                    "name": "api",
                    "kind": "custom",
                    "image": "example/api:1",
                    "depends_on": ["db"],
                }
            ],
        },
        ctx,
    )

    assert result.blocked is True
    assert result.reason == "invalid_dependency"
    assert result.dependency is not None
    assert result.dependency.valid is False
    secrets_dir = tmp_project / ".docker-agent" / "secrets"
    assert list(secrets_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_blocks_dependency_cycle_before_writing_secrets(
    tmp_project: Path,
) -> None:
    ctx = _ctx(tmp_project)
    result = await _plan(
        {
            "stackName": "app",
            "intent": "workers",
            "services": [
                {
                    "name": "api",
                    "kind": "custom",
                    "image": "example/api:1",
                    "depends_on": ["worker"],
                },
                {
                    "name": "worker",
                    "kind": "custom",
                    "image": "example/worker:1",
                    "depends_on": ["api"],
                },
            ],
        },
        ctx,
    )

    assert result.blocked is True
    assert result.reason == "invalid_dependency"
    assert result.dependency is not None
    assert result.dependency.valid is False
    secrets_dir = tmp_project / ".docker-agent" / "secrets"
    assert list(secrets_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_auto_replaces_weak_postgres_password_with_generated_value(
    tmp_project: Path,
) -> None:
    ctx = _ctx(tmp_project)
    result = await _plan(
        {
            "stackName": "weakpw",
            "intent": "postgres with weak password",
            "services": [
                {
                    "name": "db",
                    "kind": "catalog",
                    "catalogId": "postgresql:16",
                    "environment": {"POSTGRES_PASSWORD": "postgres"},
                }
            ],
        },
        ctx,
    )

    assert result.blocked is False
    assert any(
        item.service == "db" and "POSTGRES_PASSWORD" in item.keys
        for item in result.auto_generated_secrets
    )
    env_path = tmp_project / ".docker-agent" / "secrets" / "weakpw-db.env"
    env_content = env_path.read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD=postgres" not in env_content
    assert re.search(r"POSTGRES_PASSWORD=.+", env_content)


@pytest.mark.asyncio
async def test_blocks_when_service_count_exceeds_limit(tmp_project: Path) -> None:
    ctx = _ctx(tmp_project)
    services = [
        {
            "name": f"svc{i}",
            "kind": "custom",
            "image": "nginx:1.27-alpine",
        }
        for i in range(26)
    ]
    result = await _plan(
        {
            "stackName": "toobig",
            "intent": "too many services",
            "services": services,
        },
        ctx,
    )

    assert result.blocked is True
    assert result.reason == "resource_limit"


@pytest.mark.asyncio
async def test_blocks_postgres_5432_published_to_host(tmp_project: Path) -> None:
    ctx = _ctx(tmp_project)
    result = await _plan(
        {
            "stackName": "dbexposed",
            "intent": "postgres exposed",
            "services": [
                {
                    "name": "db",
                    "kind": "catalog",
                    "catalogId": "postgresql:16",
                    "exposure": "public",
                    "hostPort": 5432,
                }
            ],
        },
        ctx,
    )

    assert result.blocked is True
    assert result.reason == "db_port_exposed"


@pytest.mark.asyncio
async def test_blocks_path_traversal_in_config_file_mount(
    tmp_project: Path,
) -> None:
    ctx = _ctx(tmp_project)
    result = await _plan(
        {
            "stackName": "traversal",
            "intent": "path traversal",
            "services": [
                {
                    "name": "web",
                    "kind": "custom",
                    "image": "nginx:1.27-alpine",
                    "configMounts": [
                        {"hostPath": "../../etc", "containerPath": "/etc:ro"}
                    ],
                }
            ],
        },
        ctx,
    )

    assert result.blocked is True
    assert result.reason == "unsafe_volume"


@pytest.mark.asyncio
async def test_blocks_running_container_port_collision_before_writing_secrets(
    tmp_project: Path,
) -> None:
    engine = MockDockerEngine()
    engine.containers.append(
        {
            "Id": "existing",
            "Names": ["/existing"],
            "State": "running",
            "Labels": {},
        }
    )
    engine.inspect_by_id["existing"] = {
        "Id": "existing",
        "NetworkSettings": {
            "Ports": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]}
        },
    }
    ctx = _ctx(tmp_project, engine=engine)
    result = await _plan(
        {
            "stackName": "app",
            "intent": "api",
            "services": [
                {
                    "name": "api",
                    "kind": "custom",
                    "image": "example/api:1",
                    "exposure": "public",
                    "hostPort": 8080,
                }
            ],
        },
        ctx,
    )

    assert result.blocked is True
    assert result.reason == "port_conflict"
    secrets_dir = tmp_project / ".docker-agent" / "secrets"
    assert list(secrets_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_custom_network_name_generated_when_network_name_provided(
    tmp_project: Path,
) -> None:
    ctx = _ctx(tmp_project)
    result = await _plan(
        {
            "stackName": "test-net",
            "intent": "nginx",
            "networkName": "custom-wp-net",
            "services": [
                {
                    "name": "nginx",
                    "kind": "custom",
                    "image": "nginx:1.27-alpine",
                }
            ],
        },
        ctx,
    )

    assert result.blocked is False
    assert "custom-wp-net" in result.compose_yaml
    parsed = yaml.safe_load(result.compose_yaml)
    assert parsed["networks"]["default"]["name"] == "custom-wp-net"


@pytest.mark.asyncio
async def test_volume_name_does_not_contain_stack_name_prefix_in_yaml(
    tmp_project: Path,
) -> None:
    ctx = _ctx(tmp_project)
    result = await _plan(
        {
            "stackName": "my-stack",
            "intent": "mysql",
            "services": [
                {
                    "name": "db",
                    "kind": "catalog",
                    "catalogId": "mysql:8.0",
                    "persistence": {"size": "10Gi"},
                }
            ],
        },
        ctx,
    )

    assert result.blocked is False
    parsed = yaml.safe_load(result.compose_yaml)
    assert parsed["volumes"]["db_data"] is not None
    assert parsed["volumes"].get("my-stack_db_data") is None
    assert "db_data:" in parsed["services"]["db"]["volumes"][0]


@pytest.mark.asyncio
async def test_auto_injects_database_healthcheck_and_upgrades_depends_on(
    tmp_project: Path,
) -> None:
    ctx = _ctx(tmp_project)
    result = await _plan(
        {
            "stackName": "webapp-stack",
            "intent": "wordpress + mysql",
            "services": [
                {
                    "name": "db",
                    "kind": "custom",
                    "image": "mysql:8.0",
                    "environment": {"MYSQL_ROOT_PASSWORD": "secretpassword"},
                },
                {
                    "name": "web",
                    "kind": "custom",
                    "image": "wordpress:latest",
                    "depends_on": ["db"],
                },
            ],
        },
        ctx,
    )

    assert result.blocked is False
    parsed = yaml.safe_load(result.compose_yaml)
    assert parsed["services"]["db"]["healthcheck"] is not None
    assert parsed["services"]["db"]["healthcheck"]["test"] == [
        "CMD",
        "mysqladmin",
        "ping",
        "-h",
        "localhost",
    ]
    assert parsed["services"]["db"]["healthcheck"]["start_period"] == "30s"
    assert parsed["services"]["web"]["depends_on"] == {
        "db": {"condition": "service_healthy"}
    }