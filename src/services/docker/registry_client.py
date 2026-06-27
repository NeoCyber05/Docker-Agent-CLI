"""Async Docker registry client for image manifest checks.

Parity: ``src/services/docker/registryClient.ts``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Literal
from urllib.parse import urlencode

import httpx

from src.services.docker.image_reference import ImageReference, parse_image_reference

RegistryCheckStatus = Literal["exists", "missing", "unknown"]


class RegistryCheckStatusValues:
    """String constants for registry check status (test / validator convenience)."""

    EXISTS: RegistryCheckStatus = "exists"
    MISSING: RegistryCheckStatus = "missing"
    UNKNOWN: RegistryCheckStatus = "unknown"


@dataclass(frozen=True)
class RegistryCheckResult:
    image: str
    status: RegistryCheckStatus
    registry: str
    repository: str
    reference: str
    error: str | None = None
    suggestion: str | None = None


MANIFEST_ACCEPT = (
    "application/vnd.docker.distribution.manifest.v2+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.oci.image.manifest.v1+json"
)


@dataclass
class _BearerChallenge:
    realm: str
    service: str | None = None
    scope: str | None = None


def _parse_bearer_challenge(header: str) -> _BearerChallenge | None:
    if not header.startswith("Bearer "):
        return None
    rest = header[len("Bearer ") :]
    parts: dict[str, str] = {}
    for match in re.finditer(r'(\w+)="([^"]+)"', rest):
        parts[match.group(1)] = match.group(2)
    realm = parts.get("realm")
    if not realm:
        return None
    return _BearerChallenge(
        realm=realm, service=parts.get("service"), scope=parts.get("scope")
    )


async def _request_bearer_token(
    challenge: _BearerChallenge, client: httpx.AsyncClient
) -> str | None:
    params: dict[str, str] = {}
    if challenge.service:
        params["service"] = challenge.service
    if challenge.scope:
        params["scope"] = challenge.scope
    url = challenge.realm
    if params:
        sep = "&" if "?" in url else "?"
        url += sep + urlencode(params)
    response = await client.get(url)
    if response.status_code != 200:
        return None
    body = response.json()
    token = body.get("token") or body.get("access_token")
    return str(token) if token is not None else None


def _manifest_url(registry: str, repository: str, reference: str) -> str:
    return f"https://{registry}/v2/{repository}/manifests/{reference}"


def _tags_url(registry: str, repository: str) -> str:
    return f"https://{registry}/v2/{repository}/tags/list?n=100"


def _suggest_tag(image: str, tags: list[str]) -> str | None:
    ref = parse_image_reference(image)
    if ref.reference_type != "tag":
        return None
    if "latest" in tags:
        base = image.rsplit(":", 1)[0] if ":" in image else image
        return f"{base}:latest"
    return None


class RegistryClient:
    def __init__(self, client: httpx.AsyncClient | None = None, timeout_ms: int = 10_000) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_ms / 1000.0)

    async def check_image_exists(
        self, image: str, *, signal: Any | None = None
    ) -> RegistryCheckResult:
        ref = parse_image_reference(image)
        base = RegistryCheckResult(
            image=ref.original,
            status="unknown",
            registry=ref.registry,
            repository=ref.repository,
            reference=ref.reference,
        )
        headers = {"Accept": MANIFEST_ACCEPT}
        token: str | None = None

        try:
            url = _manifest_url(ref.registry, ref.repository, ref.reference)
            response = await self._client.head(url, headers=headers)

            if response.status_code == 401:
                challenge = _parse_bearer_challenge(
                    response.headers.get("WWW-Authenticate", "")
                )
                if challenge is None:
                    return replace(base, error="registry requires unsupported auth")
                token = await _request_bearer_token(challenge, self._client)
                if token is None:
                    return replace(base, error="registry token request failed")
                auth_headers = {**headers, "Authorization": f"Bearer {token}"}
                response = await self._client.head(url, headers=auth_headers)

            if response.status_code == 405:
                auth_headers = (
                    {**headers, "Authorization": f"Bearer {token}"} if token else headers
                )
                response = await self._client.get(url, headers=auth_headers)

            if response.is_success:
                return replace(base, status="exists")
            if response.status_code == 404:
                suggestion = await self._suggest_tag(ref)
                return replace(
                    base,
                    status="missing",
                    error="manifest not found",
                    suggestion=suggestion,
                )
            if response.status_code in (401, 403):
                return replace(base, error="registry requires authentication")
            return replace(
                base,
                error=f"registry returned {response.status_code} {response.reason_phrase}",
            )
        except Exception as err:  # noqa: BLE001
            return replace(base, error=str(err))

    async def _suggest_tag(self, ref: ImageReference) -> str | None:
        url = _tags_url(ref.registry, ref.repository)
        try:
            response = await self._client.get(url)
            if not response.is_success:
                return None
            tags = response.json().get("tags", [])
            if not isinstance(tags, list):
                return None
            str_tags = [t for t in tags if isinstance(t, str)]
            return _suggest_tag(f"{ref.original}", str_tags)
        except Exception:  # noqa: BLE001
            return None


def create_registry_client(
    client: httpx.AsyncClient | None = None, timeout_ms: int = 10_000
) -> RegistryClient:
    return RegistryClient(client=client, timeout_ms=timeout_ms)


__all__ = [
    "RegistryCheckResult",
    "RegistryCheckStatus",
    "RegistryCheckStatusValues",
    "RegistryClient",
    "create_registry_client",
]