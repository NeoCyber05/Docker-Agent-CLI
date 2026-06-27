"""Parity tests for docker service types — mirrors engineClient.ts schema subset."""

from docker_agent.services.docker.types import (
    ContainerInspect,
    ContainerSummary,
    ImageInspect,
    ImageSummary,
)


def test_container_summary_parses() -> None:
    s = ContainerSummary.model_validate(
        {"Id": "abc", "Names": ["/web"], "State": "running", "Labels": {"k": "v"}}
    )
    assert s.id == "abc"
    assert s.state == "running"


def test_container_inspect_parses_docker_py_shape() -> None:
    raw = {
        "Id": "abc",
        "Name": "/web",
        "State": {"Status": "running", "Health": {"Status": "healthy"}},
        "Config": {
            "Image": "nginx:1.27",
            "Env": ["KEY=value"],
            "Cmd": ["nginx", "-g", "daemon off;"],
            "Labels": {"com.docker.compose.service": "web"},
        },
        "HostConfig": {"Binds": ["/host:/container"], "PortBindings": {}},
        "NetworkSettings": {"Ports": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]}},
        "RestartCount": 2,
    }
    insp = ContainerInspect.model_validate(raw)
    assert insp.config.image == "nginx:1.27"
    assert insp.state.status == "running"
    assert insp.state.health is not None
    assert insp.state.health.status == "healthy"
    assert insp.restart_count == 2


def test_image_summary_normalizes_null_repo_tags() -> None:
    s = ImageSummary.model_validate(
        {"Id": "sha:abc", "RepoTags": None, "Size": 100, "Created": 123}
    )
    assert s.repo_tags == []


def test_image_inspect_parses() -> None:
    img = ImageInspect.model_validate(
        {
            "Id": "sha:abc",
            "RepoTags": ["nginx:1.27"],
            "Size": 100,
            "Architecture": "amd64",
            "Os": "linux",
            "Created": "2024-01-01T00:00:00Z",
        }
    )
    assert img.size == 100