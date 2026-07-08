"""Tests for db_app_wiring."""

from __future__ import annotations

from pathlib import Path

from docker_mcp_server.tools.shared.db_app_wiring import (
    check_db_app_credential_consistency,
    infer_implicit_db_dependencies,
    wire_dependent_app_secrets,
)
from docker_mcp_server.tools.shared.secret_staging import SecretFileStager
from docker_mcp_server.types.stack import ServiceSpec


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


def test_infer_implicit_db_dependencies_from_wordpress_db_host() -> None:
    services = {
        "db": ServiceSpec(image="mysql:8.0"),
        "wordpress": ServiceSpec(
            image="wordpress:latest",
            environment={"WORDPRESS_DB_HOST": "db"},
        ),
    }

    assert infer_implicit_db_dependencies(services) == 1
    assert services["wordpress"].depends_on == ["db"]


def test_wire_wordpress_mysql_wp_user_without_depends_on(tmp_path: Path) -> None:
    secrets_dir = tmp_path / ".docker-agent" / "secrets"
    secrets_dir.mkdir(parents=True)
    db_env = secrets_dir / "stack-db.env"
    db_env.write_text(
        "MYSQL_ROOT_PASSWORD=super-secret-root\nMYSQL_PASSWORD=wp-user-secret\n",
        encoding="utf-8",
    )

    services = {
        "db": ServiceSpec(
            image="mysql:8.0",
            env_file=["./.docker-agent/secrets/stack-db.env"],
        ),
        "wordpress": ServiceSpec(
            image="wordpress:latest",
            environment={
                "WORDPRESS_DB_HOST": "db",
                "WORDPRESS_DB_USER": "wp_user",
            },
        ),
    }
    infer_implicit_db_dependencies(services)

    stager = SecretFileStager()
    wired = wire_dependent_app_secrets(
        str(tmp_path),
        "stack",
        services,
        {},
        stager,
    )

    assert ("wordpress", ["WORDPRESS_DB_PASSWORD"]) in wired
    assert (
        stager.read(secrets_dir / "stack-wordpress.env")["WORDPRESS_DB_PASSWORD"]
        == "wp-user-secret"
    )


def test_wire_wordpress_mysql_copies_root_password(tmp_path: Path) -> None:
    secrets_dir = tmp_path / ".docker-agent" / "secrets"
    secrets_dir.mkdir(parents=True)
    db_env = secrets_dir / "stack-db.env"
    db_env.write_text("MYSQL_ROOT_PASSWORD=super-secret-root\n", encoding="utf-8")

    services = _wordpress_mysql_services()
    generated_sources: dict = {}
    stager = SecretFileStager()

    wired = wire_dependent_app_secrets(
        str(tmp_path),
        "stack",
        services,
        generated_sources,
        stager,
    )

    assert ("wordpress", ["WORDPRESS_DB_PASSWORD"]) in wired
    assert ("wordpress", ["WORDPRESS_DB_NAME"]) in wired
    assert ("db", ["MYSQL_DATABASE"]) in wired

    wp_env_path = secrets_dir / "stack-wordpress.env"
    assert stager.read(wp_env_path)["WORDPRESS_DB_PASSWORD"] == "super-secret-root"
    assert services["wordpress"].environment["WORDPRESS_DB_NAME"] == "wordpress"
    assert stager.read(db_env)["MYSQL_DATABASE"] == "wordpress"
    assert "./.docker-agent/secrets/stack-wordpress.env" in (services["wordpress"].env_file or [])
    assert not wp_env_path.exists()


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

    stager = SecretFileStager()
    wired = wire_dependent_app_secrets(
        str(tmp_path),
        "stack",
        services,
        {},
        stager,
    )

    assert ("wordpress", ["WORDPRESS_DB_PASSWORD"]) not in wired
    assert (
        stager.read(secrets_dir / "stack-wordpress.env")["WORDPRESS_DB_PASSWORD"]
        == "already-set"
    )


def test_wire_wordpress_mysql_provisions_app_user_when_missing(tmp_path: Path) -> None:
    secrets_dir = tmp_path / ".docker-agent" / "secrets"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / "stack-db.env").write_text(
        "MYSQL_ROOT_PASSWORD=super-secret-root\n",
        encoding="utf-8",
    )

    services = {
        "db": ServiceSpec(
            image="mysql:8.0",
            env_file=["./.docker-agent/secrets/stack-db.env"],
        ),
        "wordpress": ServiceSpec(
            image="wordpress:latest",
            environment={
                "WORDPRESS_DB_HOST": "db",
                "WORDPRESS_DB_USER": "wordpress",
                "WORDPRESS_DB_NAME": "wordpress",
            },
            depends_on=["db"],
        ),
    }
    generated_sources: dict = {}
    stager = SecretFileStager()

    wired = wire_dependent_app_secrets(
        str(tmp_path),
        "stack",
        services,
        generated_sources,
        stager,
    )

    assert services["db"].environment == {"MYSQL_USER": "wordpress"}
    assert ("db", ["MYSQL_USER"]) in wired
    assert ("db", ["MYSQL_PASSWORD"]) in wired
    assert ("wordpress", ["WORDPRESS_DB_PASSWORD"]) in wired
    db_staged = stager.read(secrets_dir / "stack-db.env")
    wp_staged = stager.read(secrets_dir / "stack-wordpress.env")
    assert db_staged["MYSQL_PASSWORD"]
    assert wp_staged["WORDPRESS_DB_PASSWORD"] == db_staged["MYSQL_PASSWORD"]


def test_check_db_app_credential_consistency_flags_user_mismatch() -> None:
    services = {
        "db": ServiceSpec(
            image="mysql:8.0",
            environment={"MYSQL_USER": "other_user"},
        ),
        "wordpress": ServiceSpec(
            image="wordpress:latest",
            environment={
                "WORDPRESS_DB_HOST": "db",
                "WORDPRESS_DB_USER": "wordpress",
            },
            depends_on=["db"],
        ),
    }

    issues = check_db_app_credential_consistency(services)

    assert len(issues) == 1
    assert "does not match" in issues[0].message


def test_wire_node_mongo_injects_connection_uri(tmp_path: Path) -> None:
    secrets_dir = tmp_path / ".docker-agent" / "secrets"
    secrets_dir.mkdir(parents=True)
    db_env = secrets_dir / "stack-db.env"
    db_env.write_text(
        "MONGO_INITDB_ROOT_PASSWORD=generated-mongo-secret\n",
        encoding="utf-8",
    )

    services = {
        "db": ServiceSpec(
            image="mongo:6.0",
            env_file=["./.docker-agent/secrets/stack-db.env"],
        ),
        "api": ServiceSpec(
            image="node:20-alpine",
            environment={"MONGO_URI": ""},
            depends_on=["db"],
        ),
    }
    generated_sources: dict = {}
    stager = SecretFileStager()

    wired = wire_dependent_app_secrets(
        str(tmp_path),
        "stack",
        services,
        generated_sources,
        stager,
    )

    assert ("api", ["MONGO_URI"]) in wired
    api_env_path = secrets_dir / "stack-api.env"
    uri = stager.read(api_env_path)["MONGO_URI"]
    assert uri == "mongodb://root:generated-mongo-secret@db:27017/db?authSource=admin"
    assert "generated-mongo-secret" not in (services["api"].environment or {})
    assert "./.docker-agent/secrets/stack-api.env" in (services["api"].env_file or [])



