"""Parity tests for registry_client â€” mirrors src/services/docker/registryClient.ts."""

import pytest

from docker_mcp_server.services.docker.registry_client import (
    RegistryCheckStatusValues,
    create_registry_client,
)


@pytest.mark.asyncio
async def test_registry_exists(httpx_mock) -> None:
    httpx_mock.add_response(status_code=200)
    client = create_registry_client()
    result = await client.check_image_exists("nginx:1.27")
    assert result.status == RegistryCheckStatusValues.EXISTS
    assert result.registry == "registry-1.docker.io"
    assert result.repository == "library/nginx"


@pytest.mark.asyncio
async def test_registry_missing_suggests_latest(httpx_mock) -> None:
    httpx_mock.add_response(status_code=404)
    httpx_mock.add_response(json={"tags": ["latest", "1.27"]})
    client = create_registry_client()
    result = await client.check_image_exists("nginx:missing")
    assert result.status == RegistryCheckStatusValues.MISSING
    assert "latest" in (result.suggestion or "")


@pytest.mark.asyncio
async def test_registry_bearer_auth(httpx_mock) -> None:
    challenge = (
        'Bearer realm="https://auth.docker.io/token",'
        'service="registry.docker.io",scope="repository:library/nginx:pull"'
    )
    httpx_mock.add_response(status_code=401, headers={"WWW-Authenticate": challenge})
    httpx_mock.add_response(json={"token": "abc123"})
    httpx_mock.add_response(status_code=200)
    client = create_registry_client()
    result = await client.check_image_exists("nginx")
    assert result.status == RegistryCheckStatusValues.EXISTS


