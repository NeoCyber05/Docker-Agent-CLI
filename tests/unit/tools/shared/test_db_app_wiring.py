"""Tests for db_app_wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from docker_agent.state.env_file import read_env_file
from docker_agent.tools.shared.db_app_wiring import wire_dependent_app_secrets
from docker_agent.types.stack import ServiceSpec


def _wordpress_mysql_services() -> dict[str, ServiceSpec]:
    return {
        "db": ServiceSpec(
            image="mysql:8.0",
            env_file=["./.docker-agent/secrets/stack-db.env"],
        ),
        "wordpress": ServiceSpec(
            image="wordpress:latest",
            environment={
                "WORDPRESS_DB_HOST": "db",
                "WORDPRESS_DB_USER": "root",
            },
            depends_on=["db"],
        ),
    }


def test_wire_wordpress_mysql_copies_root_password(tmp_path: Path) -> None:
    secrets_dir = tmp_path / ".docker-agent" / "secrets"
    secrets_dir.mkdir(parents=True)
    db_env = secrets_dir / "stack-db.env"
    db_env.write_text("MYSQL_ROOT_PASSWORD=super-secret-root\n", encoding="utf-8")

    services = _wordpress_mysql_services()
    generated_sources: dict = {}

    wired = wire_dependent_app_secrets(
        str(tmp_path),
        "stack",
        services,
        generated_sources,
    )

    assert ("wordpress", ["WORDPRESS_DB_PASSWORD"]) in wired
    assert ("wordpress", ["WORDPRESS_DB_NAME"]) in wired
    assert ("db", ["MYSQL_DATABASE"]) in wired

    wp_env = read_env_file(secrets_dir / "stack-wordpress.env")
    assert wp_env["WORDPRESS_DB_PASSWORD"] == "super-secret-root"
    assert services["wordpress"].environment["WORDPRESS_DB_NAME"] == "wordpress"
    assert read_env_file(db_env)["MYSQL_DATABASE"] == "wordpress"
    assert "./.docker-agent/secrets/stack-wordpress.env" in (services["wordpress"].env_file or [])


def test_wire_wordpress_mysql_does_not_overwrite_existing_password(tmp_path: Path) -> None:
    secrets_dir = tmp_path / ".docker-agent" / "secrets"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / "stack-db.env").write_text(
        "MYSQL_ROOT_PASSWORD=db-secret\n", encoding="utf-8"
    )
    (secrets_dir / "stack-wordpress.env").write_text(
        "WORDPRESS_DB_PASSWORD=already-set\n", encoding="utf-8"
    )

    services = _wordpress_mysql_services()
    services["wordpress"] = services["wordpress"].model_copy(
        update={"env_file": ["./.docker-agent/secrets/stack-wordpress.env"]}
    )

    wired = wire_dependent_app_secrets(
        str(tmp_path),
        "stack",
        services,
        {},
    )

    assert ("wordpress", ["WORDPRESS_DB_PASSWORD"]) not in wired
    assert read_env_file(secrets_dir / "stack-wordpress.env")["WORDPRESS_DB_PASSWORD"] == "already-set"
