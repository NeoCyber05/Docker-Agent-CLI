"""Parity tests for volume_guard â€” mirrors src/tools/shared/__tests__/volumeGuard.test.ts."""

from docker_mcp_server.tools.shared.volume_guard import check_volume_safety
from docker_mcp_server.types.stack import ServiceSpec


def _svc(volumes: list[str]) -> ServiceSpec:
    return ServiceSpec(image="nginx:1.27-alpine", volumes=volumes)


def test_passes_for_named_volume() -> None:
    assert check_volume_safety("/app", {"web": _svc(["data:/data"])}) == []


def test_passes_for_safe_relative_bind_mount_inside_cwd() -> None:
    assert check_volume_safety("/app", {"web": _svc(["./config:/config:ro"])}) == []


def test_blocks_path_traversal_with_dotdot_that_escapes_cwd() -> None:
    issues = check_volume_safety("/app", {"web": _svc(["../../etc:/etc:ro"])})
    assert len(issues) == 1
    assert issues[0].code == "path_traversal"
    assert issues[0].volume == "../../etc:/etc:ro"


def test_blocks_docker_sock_bind_mount() -> None:
    issues = check_volume_safety(
        "/app",
        {"web": _svc(["/var/run/docker.sock:/var/run/docker.sock"])},
    )
    assert len(issues) == 1
    assert issues[0].code == "sensitive_host_path"


def test_blocks_etc_proc_sys_boot_bind_mounts() -> None:
    issues = check_volume_safety(
        "/app",
        {
            "a": _svc(["/etc:/etc:ro"]),
            "b": _svc(["/proc:/proc:ro"]),
            "c": _svc(["/sys:/sys:ro"]),
            "d": _svc(["/boot:/boot:ro"]),
        },
    )
    assert len(issues) == 4
    assert all(issue.code == "sensitive_host_path" for issue in issues)


def test_blocks_ssh_bind_mount() -> None:
    issues = check_volume_safety(
        "/app", {"web": _svc(["~/.ssh:/root/.ssh:ro"])}
    )
    assert len(issues) == 1
    assert issues[0].code == "sensitive_host_path"


def test_check_volume_references_passes_when_declared() -> None:
    from docker_mcp_server.tools.shared.volume_guard import check_volume_references

    assert (
        check_volume_references(
            {"web": _svc(["data:/data"])},
            {"data": {}},
        )
        == []
    )


def test_check_volume_references_blocks_undeclared() -> None:
    from docker_mcp_server.tools.shared.volume_guard import check_volume_references

    issues = check_volume_references({"web": _svc(["ghost:/data"])}, {"data": {}})
    assert len(issues) == 1
    assert issues[0].code == "undeclared_volume"
    assert issues[0].volume == "ghost:/data"


def test_check_volume_references_ignores_bind_mounts() -> None:
    from docker_mcp_server.tools.shared.volume_guard import check_volume_references

    assert (
        check_volume_references(
            {"web": _svc(["./config:/config:ro"])},
            {},
        )
        == []
    )


