"""Parity tests for config_files â€” mirrors src/tools/shared/__tests__/configFiles.test.ts."""

from pathlib import Path

import pytest

from docker_mcp_server.tools.shared.config_files import (
    detect_missing_config_files,
    find_invalid_file_binds,
    is_file_like_bind,
    parse_bind_mount,
    resolve_safe,
    restore_config_files,
    snapshot_config_files,
    stage_config_files,
    write_config_files,
)
from docker_mcp_server.types.stack import ServiceSpec


def test_parse_bind_mount_relative() -> None:
    bind = parse_bind_mount("./nginx.conf:/etc/nginx/nginx.conf")
    assert bind is not None
    assert bind.source == "./nginx.conf"
    assert bind.target == "/etc/nginx/nginx.conf"
    assert bind.mode is None


def test_parse_bind_mount_captures_mode_suffix() -> None:
    bind = parse_bind_mount("./nginx.conf:/etc/nginx/nginx.conf:ro")
    assert bind is not None
    assert bind.source == "./nginx.conf"
    assert bind.target == "/etc/nginx/nginx.conf"
    assert bind.mode == "ro"


def test_parse_bind_mount_returns_none_for_named_volume() -> None:
    assert parse_bind_mount("pgdata:/var/lib/postgresql/data") is None


def test_is_file_like_bind() -> None:
    assert is_file_like_bind("./nginx.conf") is True
    assert is_file_like_bind("./conf/app.yaml") is True
    assert is_file_like_bind("./data") is False
    assert is_file_like_bind("./html") is False


@pytest.fixture
def cwd(tmp_path: Path) -> Path:
    return tmp_path


def test_resolve_safe_accepts_in_cwd_relative_path(cwd: Path) -> None:
    result = resolve_safe(cwd, "./nginx.conf")
    assert result["ok"] is True
    assert result["abs"] == str(cwd / "nginx.conf")


def test_resolve_safe_rejects_path_traversal(cwd: Path) -> None:
    assert resolve_safe(cwd, "../escape.conf")["ok"] is False


def test_resolve_safe_rejects_absolute_path(cwd: Path) -> None:
    assert resolve_safe(cwd, "/etc/passwd")["ok"] is False


def test_resolve_safe_rejects_reserved_infra_agent_subtree(cwd: Path) -> None:
    assert resolve_safe(cwd, "./.docker-agent/x.env")["ok"] is False


def test_detect_missing_config_files_reports_missing_bind(cwd: Path) -> None:
    services = {
        "nginx": ServiceSpec(
            image="nginx", volumes=["./nginx.conf:/etc/nginx/nginx.conf"]
        )
    }
    assert detect_missing_config_files(services, set(), cwd) == [
        {"service": "nginx", "path": "./nginx.conf"}
    ]


def test_detect_missing_config_files_skips_when_content_provided(cwd: Path) -> None:
    services = {
        "nginx": ServiceSpec(
            image="nginx", volumes=["./nginx.conf:/etc/nginx/nginx.conf"]
        )
    }
    assert detect_missing_config_files(services, {"nginx.conf"}, cwd) == []


def test_detect_missing_config_files_ignores_directory_mount(cwd: Path) -> None:
    services = {
        "web": ServiceSpec(image="nginx", volumes=["./html:/usr/share/nginx/html"])
    }
    assert detect_missing_config_files(services, set(), cwd) == []


def test_detect_missing_config_files_skips_existing_host_file(cwd: Path) -> None:
    (cwd / "nginx.conf").write_text("x", encoding="utf-8")
    services = {
        "nginx": ServiceSpec(
            image="nginx", volumes=["./nginx.conf:/etc/nginx/nginx.conf"]
        )
    }
    assert detect_missing_config_files(services, set(), cwd) == []


def test_find_invalid_file_binds_flags_missing_source(cwd: Path) -> None:
    services = {
        "nginx": ServiceSpec(
            image="nginx",
            volumes=["./nginx.conf:/etc/nginx/nginx.conf:ro"],
        )
    }
    assert find_invalid_file_binds(services, cwd) == [
        {"service": "nginx", "path": "./nginx.conf", "reason": "missing"}
    ]


def test_find_invalid_file_binds_flags_directory_squatter(cwd: Path) -> None:
    (cwd / "nginx.conf").mkdir()
    services = {
        "nginx": ServiceSpec(
            image="nginx",
            volumes=["./nginx.conf:/etc/nginx/nginx.conf:ro"],
        )
    }
    assert find_invalid_file_binds(services, cwd) == [
        {"service": "nginx", "path": "./nginx.conf", "reason": "directory"}
    ]


def test_find_invalid_file_binds_accepts_real_file(cwd: Path) -> None:
    (cwd / "nginx.conf").write_text("events {}", encoding="utf-8")
    services = {
        "nginx": ServiceSpec(
            image="nginx",
            volumes=["./nginx.conf:/etc/nginx/nginx.conf:ro"],
        )
    }
    assert find_invalid_file_binds(services, cwd) == []


def test_find_invalid_file_binds_ignores_directory_and_named_volumes(cwd: Path) -> None:
    services = {
        "web": ServiceSpec(
            image="nginx",
            volumes=["./html:/usr/share/nginx/html", "pgdata:/var/lib/x"],
        )
    }
    assert find_invalid_file_binds(services, cwd) == []


def test_write_config_files_replaces_directory_with_file(cwd: Path) -> None:
    from docker_mcp_server.tools.shared.config_files import StagedConfigFile

    (cwd / "nginx.conf").mkdir()
    write_config_files(
        cwd, [StagedConfigFile(path="nginx.conf", content="events {}", bytes=9)]
    )
    target = cwd / "nginx.conf"
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "events {}"


def test_stage_config_files_stages_matching_bind(cwd: Path) -> None:
    from docker_mcp_server.tools.shared.config_files import StagedConfigFile

    nginx = {
        "nginx": ServiceSpec(
            image="nginx", volumes=["./nginx.conf:/etc/nginx/nginx.conf"]
        )
    }
    result = stage_config_files(cwd, nginx, {"./nginx.conf": "events {}"})
    assert result["ok"] is True
    staged = result["staged"]
    assert staged == [
        StagedConfigFile(path="nginx.conf", content="events {}", bytes=9)
    ]


def test_stage_config_files_rejects_unsafe_path(cwd: Path) -> None:
    nginx = {
        "nginx": ServiceSpec(
            image="nginx", volumes=["./nginx.conf:/etc/nginx/nginx.conf"]
        )
    }
    assert stage_config_files(cwd, nginx, {"../evil.conf": "x"})["ok"] is False


def test_stage_config_files_rejects_dangling_content(cwd: Path) -> None:
    nginx = {
        "nginx": ServiceSpec(
            image="nginx", volumes=["./nginx.conf:/etc/nginx/nginx.conf"]
        )
    }
    assert stage_config_files(cwd, nginx, {"./unused.conf": "x"})["ok"] is False


def test_stage_config_files_rejects_file_over_64_kib(cwd: Path) -> None:
    nginx = {
        "nginx": ServiceSpec(
            image="nginx", volumes=["./nginx.conf:/etc/nginx/nginx.conf"]
        )
    }
    assert stage_config_files(cwd, nginx, {"./nginx.conf": "a" * (64 * 1024 + 1)})["ok"] is False


def test_write_then_restore_removes_newly_created_file(cwd: Path) -> None:
    from docker_mcp_server.tools.shared.config_files import StagedConfigFile

    staged = [StagedConfigFile(path="nginx.conf", content="events {}", bytes=9)]
    snaps = snapshot_config_files(cwd, staged)
    write_config_files(cwd, staged)
    assert (cwd / "nginx.conf").exists()
    restore_config_files(snaps)
    assert not (cwd / "nginx.conf").exists()


def test_write_then_restore_brings_back_overwritten_content(cwd: Path) -> None:
    from docker_mcp_server.tools.shared.config_files import StagedConfigFile

    (cwd / "nginx.conf").write_text("ORIGINAL", encoding="utf-8")
    staged = [StagedConfigFile(path="nginx.conf", content="NEW", bytes=3)]
    snaps = snapshot_config_files(cwd, staged)
    write_config_files(cwd, staged)
    assert (cwd / "nginx.conf").read_text(encoding="utf-8") == "NEW"
    restore_config_files(snaps)
    assert (cwd / "nginx.conf").read_text(encoding="utf-8") == "ORIGINAL"


