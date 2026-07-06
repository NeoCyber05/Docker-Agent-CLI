"""Parity tests for db_port_guard â€” mirrors src/tools/shared/__tests__/dbPortGuard.test.ts."""

from docker_mcp_server.tools.shared.db_port_guard import DB_PORT_MAP, check_db_port_exposure
from docker_mcp_server.types.stack import ServiceSpec


def test_db_port_map_covers_expected_labels() -> None:
    labels = sorted(entry.label for entry in DB_PORT_MAP)
    assert labels == ["mariadb", "mongo", "mysql", "postgres", "redis"]


def test_blocks_postgres_5432_published_to_host() -> None:
    issues = check_db_port_exposure(
        {"db": ServiceSpec(image="postgres:17-alpine", ports=["5432:5432"])}
    )
    assert len(issues) == 1
    assert issues[0].service == "db"
    assert issues[0].container_port == 5432


def test_allows_postgres_on_non_default_host_port() -> None:
    assert check_db_port_exposure(
        {"db": ServiceSpec(image="postgres:17-alpine", ports=["15432:5432"])}
    ) == []


def test_allows_postgres_with_no_ports() -> None:
    assert check_db_port_exposure({"db": ServiceSpec(image="postgres:17-alpine")}) == []


def test_blocks_mysql_and_redis_default_ports_simultaneously() -> None:
    issues = check_db_port_exposure(
        {
            "mysql": ServiceSpec(image="mysql:8", ports=["3306:3306"]),
            "cache": ServiceSpec(image="redis:7-alpine", ports=["6379:6379"]),
        }
    )
    assert len(issues) == 2
    assert sorted(issue.container_port for issue in issues) == [3306, 6379]


def test_ignores_non_db_images() -> None:
    assert check_db_port_exposure(
        {"web": ServiceSpec(image="nginx:1.27-alpine", ports=["80:80"])}
    ) == []


