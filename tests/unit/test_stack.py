"""Parity tests for docker_agent.types.stack — mirrors src/types/stack.ts:1-97."""

import pytest
from pydantic import ValidationError

from src.types.stack import (
    DockerAgentMeta,
    EnvFileSource,
    EnvSnapshot,
    ServiceDiff,
    ServiceSnapshot,
    ServiceSpec,
    StackDefinition,
    StackDiff,
    StackSummary,
)

# --- ServiceSpec --------------------------------------------------------

def test_service_spec_minimal() -> None:
    svc = ServiceSpec(image="nginx:1.27")
    assert svc.image == "nginx:1.27"
    assert svc.command is None
    assert svc.ports is None
    assert svc.environment is None


def test_service_spec_full_shape() -> None:
    svc = ServiceSpec.model_validate(
        {
            "image": "postgres:16",
            "command": ["postgres", "-c", "max_connections=100"],
            "ports": ["5432:5432"],
            "environment": {"POSTGRES_PASSWORD": "x"},
            "env_file": ["./.env"],
            "volumes": ["data:/var/lib/postgresql/data"],
            "depends_on": ["cache"],
            "healthcheck": {
                "test": ["CMD-SHELL", "pg_isready"],
                "interval": "10s",
                "retries": 5,
            },
            "restart": "unless-stopped",
            "labels": {"app": "db"},
            "networks": ["default"],
            "scale": 2,
            "deploy": {"resources": {"limits": {"cpus": "1", "memory": "512M"}}},
            "logging": {"driver": "json-file", "options": {"max-size": "10m"}},
            "user": "postgres",
            "read_only": False,
        }
    )
    assert svc.depends_on == ["cache"]
    assert svc.healthcheck is not None
    assert svc.healthcheck.test == ["CMD-SHELL", "pg_isready"]
    assert svc.deploy is not None
    assert svc.deploy.resources is not None
    assert svc.deploy.resources.limits is not None
    assert svc.deploy.resources.limits.cpus == "1"


def test_service_spec_depends_on_can_be_condition_map() -> None:
    svc = ServiceSpec.model_validate(
        {
            "image": "x",
            "depends_on": {
                "cache": {"condition": "service_healthy"},
                "init": {"condition": "service_completed_successfully"},
            },
        }
    )
    assert isinstance(svc.depends_on, dict)
    assert svc.depends_on["cache"]["condition"] == "service_healthy"


def test_service_spec_depends_on_unknown_condition_rejected() -> None:
    with pytest.raises(ValidationError):
        ServiceSpec.model_validate({"image": "x", "depends_on": {"c": {"condition": "bogus"}}})


def test_service_spec_restart_value_restricted() -> None:
    ServiceSpec(image="x", restart="always")
    with pytest.raises(ValidationError):
        ServiceSpec(image="x", restart="forever")  # type: ignore[arg-type]


def test_service_spec_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        ServiceSpec.model_validate({"image": "x", "sneaky": True})


# --- EnvFileSource, DockerAgentMeta, StackDefinition ---------------------

def test_env_file_source_default_added_keys_none() -> None:
    src = EnvFileSource(generated=True, path="./.docker-agent/secrets/db.env")
    assert src.generated is True
    assert src.added_keys is None


def test_docker_agent_meta_round_trip() -> None:
    meta = DockerAgentMeta(
        name="web",
        created_at="2026-06-27T00:00:00Z",
        last_applied=None,
        intent="deploy nginx",
        provider="gemini",
        generated_by="docker-agent:v0.1.0",
        env_file_sources={"./.env": EnvFileSource(generated=False, path="./.env")},
    )
    dumped = meta.model_dump(by_alias=True)
    assert dumped["createdAt"] == "2026-06-27T00:00:00Z"
    assert dumped["envFileSources"]["./.env"]["generated"] is False


def test_stack_definition_minimal_with_meta_and_services() -> None:
    payload = {
        "x-docker-agent": {
            "name": "web",
            "createdAt": "2026-06-27T00:00:00Z",
            "lastApplied": None,
            "intent": "deploy",
            "provider": "gemini",
            "generatedBy": "docker-agent:v0.1.0",
            "envFileSources": {},
        },
        "services": {"web": {"image": "nginx:1.27"}},
    }
    stack = StackDefinition.model_validate(payload)
    assert stack.x_docker_agent.name == "web"
    assert stack.services["web"].image == "nginx:1.27"


# --- StackSummary, ServiceSnapshot, EnvSnapshot --------------------------

def test_stack_summary() -> None:
    s = StackSummary(name="web", service_count=2, last_applied=None)
    assert s.service_count == 2
    dumped = s.model_dump(by_alias=True)
    assert dumped == {"name": "web", "serviceCount": 2, "lastApplied": None}


def test_service_snapshot_accepts_null_command() -> None:
    snap = ServiceSnapshot(
        image="x",
        command=None,
        ports=[],
        env=EnvSnapshot(visible={}, secret_keys=[], secret_hashes_by_key={}),
        volumes=[],
        replica_count=1,
    )
    assert snap.command is None


def test_env_snapshot_secret_hashes_by_key_alias() -> None:
    snap = EnvSnapshot.model_validate(
        {"visible": {}, "secretKeys": [], "secretHashesByKey": {"K": "h"}}
    )
    assert snap.secret_hashes_by_key == {"K": "h"}


# --- ServiceDiff, StackDiff ----------------------------------------------

def test_service_diff_changes_any_type() -> None:
    diff = ServiceDiff(
        service="web",
        desired=None,
        actual=None,
        changes=[{"field": "image", "from": "nginx:1.27", "to": "nginx:1.28"}],
    )
    assert diff.changes[0].from_ == "nginx:1.27"
    assert diff.changes[0].to == "nginx:1.28"


def test_stack_diff_status_restricted() -> None:
    StackDiff(stack_name="x", status="in_sync", service_diffs=[])
    StackDiff(stack_name="x", status="drift", service_diffs=[])
    with pytest.raises(ValidationError):
        StackDiff(stack_name="x", status="combined", service_diffs=[])  # type: ignore[arg-type]


# --- Round-trip a complex StackDefinition through YAML ------------------

def test_stack_definition_full_round_trip_json() -> None:
    import json

    payload = {
        "x-docker-agent": {
            "name": "web",
            "createdAt": "2026-06-27T00:00:00Z",
            "lastApplied": "2026-06-27T00:01:00Z",
            "intent": "deploy nginx",
            "provider": "gemini",
            "generatedBy": "docker-agent:v0.1.0",
            "envFileSources": {"./.env": {"generated": False, "path": "./.env"}},
        },
        "services": {
            "web": {
                "image": "nginx:1.27",
                "ports": ["80:80"],
                "restart": "unless-stopped",
                "depends_on": ["cache"],
                "healthcheck": {"test": ["CMD", "nginx", "-t"], "interval": "30s"},
            }
        },
        "networks": {"default": {}},
    }
    parsed = StackDefinition.model_validate(payload)
    re_dumped = json.loads(parsed.model_dump_json(by_alias=True, exclude_none=True))
    assert re_dumped == payload