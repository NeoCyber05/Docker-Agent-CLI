"""
Docker image reference parsing and normalization.
"""

from dataclasses import dataclass
from typing import Literal

DEFAULT_DOCKER_HUB_REGISTRY = "registry-1.docker.io"
DEFAULT_TAG = "latest"


@dataclass(frozen=True)
class ImageReference:
    original: str
    registry: str
    repository: str
    reference: str
    reference_type: Literal["tag", "digest"]
    normalized: str


def _is_explicit_registry(part: str) -> bool:
    return part == "localhost" or "." in part or ":" in part


def _normalize_repository(repository: str, registry: str) -> str:
    if registry == DEFAULT_DOCKER_HUB_REGISTRY and "/" not in repository:
        return f"library/{repository}"
    return repository


def _normalize_registry(registry: str) -> str:
    if registry in ("docker.io", "index.docker.io"):
        return DEFAULT_DOCKER_HUB_REGISTRY
    return registry


def parse_image_reference(input: str) -> ImageReference:
    """Parse a Docker image reference into its components."""
    input = input.strip()
    if not input:
        raise ValueError("Docker image reference is required")

    at = input.find("@")
    if at >= 0:
        name_part = input[:at]
        digest_part = input[at + 1 :]
        if not name_part:
            raise ValueError(f"Invalid Docker image reference: {input}")
    else:
        name_part = input
        digest_part = None

    slash_index = name_part.find("/")
    first_part = name_part[:slash_index] if slash_index >= 0 else name_part
    has_explicit_registry = slash_index >= 0 and _is_explicit_registry(first_part)
    if has_explicit_registry:
        registry = _normalize_registry(first_part)
        remainder = name_part[slash_index + 1 :]
    else:
        registry = DEFAULT_DOCKER_HUB_REGISTRY
        remainder = name_part

    last_slash = remainder.rfind("/")
    candidate = remainder[last_slash + 1 :]
    if ":" in candidate:
        colon = remainder.rfind(":")
        repository = remainder[:colon]
        reference = remainder[colon + 1 :]
    else:
        repository = remainder
        reference = DEFAULT_TAG

    repository = _normalize_repository(repository, registry)

    if digest_part:
        normalized = f"{registry}/{repository}@{digest_part}"
        reference_type: Literal["tag", "digest"] = "digest"
        reference = digest_part
    else:
        normalized = f"{registry}/{repository}:{reference}"
        reference_type = "tag"

    return ImageReference(
        original=input,
        registry=registry,
        repository=repository,
        reference=reference,
        reference_type=reference_type,
        normalized=normalized,
    )


__all__ = ["ImageReference", "parse_image_reference"]
