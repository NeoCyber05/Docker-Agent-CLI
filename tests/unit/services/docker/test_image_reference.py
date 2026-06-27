"""Parity tests for image_reference — mirrors src/services/docker/imageReference.ts."""

import pytest

from docker_agent.services.docker.image_reference import parse_image_reference


def test_simple_docker_hub_image() -> None:
    ref = parse_image_reference("nginx")
    assert ref.registry == "registry-1.docker.io"
    assert ref.repository == "library/nginx"
    assert ref.reference == "latest"
    assert ref.reference_type == "tag"
    assert ref.normalized == "registry-1.docker.io/library/nginx:latest"


def test_tagged_docker_hub_image() -> None:
    ref = parse_image_reference("nginx:1.27")
    assert ref.reference == "1.27"
    assert ref.normalized == "registry-1.docker.io/library/nginx:1.27"


def test_explicit_docker_io_alias() -> None:
    ref = parse_image_reference("docker.io/nginx")
    assert ref.registry == "registry-1.docker.io"


def test_private_registry() -> None:
    ref = parse_image_reference("my.registry.com/org/app:v1.2")
    assert ref.registry == "my.registry.com"
    assert ref.repository == "org/app"
    assert ref.reference == "v1.2"


def test_localhost_registry() -> None:
    ref = parse_image_reference("localhost:5000/app")
    assert ref.registry == "localhost:5000"
    assert ref.repository == "app"


def test_digest_reference() -> None:
    ref = parse_image_reference(
        "nginx@sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    )
    assert ref.reference_type == "digest"
    assert ref.reference.startswith("sha256:")
    assert ref.normalized.startswith("registry-1.docker.io/library/nginx@sha256:")


def test_empty_raises() -> None:
    with pytest.raises(ValueError, match="required"):
        parse_image_reference("")


def test_user_repo_no_library_prefix() -> None:
    ref = parse_image_reference("user/nginx")
    assert ref.repository == "user/nginx"
    assert not ref.repository.startswith("library/")