"""Wire auto-generated database secrets into dependent application services."""

from __future__ import annotations

import re
from pathlib import Path

from docker_agent.state.env_file import merge_env, read_env_file, write_env_file
from docker_agent.tools.shared.db_healthcheck import DEFAULT_DB_HEALTHCHECKS
from docker_agent.types.stack import EnvFileSource, ServiceSpec

WORDPRESS_IMAGE = re.compile(r"^wordpress(:|$)")
DEFAULT_WORDPRESS_DB_NAME = "wordpress"


def _generated_env_file_path(cwd: str, stack_name: str, service_name: str) -> Path:
    return Path(cwd) / ".docker-agent" / "secrets" / f"{stack_name}-{service_name}.env"


def _generated_env_file_ref(stack_name: str, service_name: str) -> str:
    return f"./.docker-agent/secrets/{stack_name}-{service_name}.env"


def _resolve_env_file(cwd: str, ref_path: str) -> Path:
    return Path(cwd).resolve() / ref_path


def _is_db_image(image: str) -> bool:
    return any(rule.image_pattern.search(image) for rule in DEFAULT_DB_HEALTHCHECKS)


def _db_dependency_names(spec: ServiceSpec, services: dict[str, ServiceSpec]) -> list[str]:
    depends_on = spec.depends_on
    if depends_on is None:
        return []
    if isinstance(depends_on, list):
        dep_names = depends_on
    else:
        dep_names = list(depends_on.keys())
    return [name for name in dep_names if name in services and _is_db_image(services[name].image)]


def _merged_service_env(cwd: str, spec: ServiceSpec) -> dict[str, str]:
    from_env_file: dict[str, str] = {}
    for env_file_path in spec.env_file or []:
        from_env_file.update(read_env_file(_resolve_env_file(cwd, env_file_path)))
    return merge_env(from_env_file, spec.environment or {})


def _mysql_family_keys(db_image: str, app_db_user: str) -> tuple[str, str] | None:
    if re.search(r"^mysql(:|$)", db_image):
        password_key = (
            "MYSQL_ROOT_PASSWORD" if app_db_user == "root" else "MYSQL_PASSWORD"
        )
        return password_key, "MYSQL_DATABASE"
    if re.search(r"^mariadb(:|$)", db_image):
        password_key = (
            "MARIADB_ROOT_PASSWORD" if app_db_user == "root" else "MARIADB_PASSWORD"
        )
        return password_key, "MARIADB_DATABASE"
    return None


def _ensure_env_file_value(
    *,
    cwd: str,
    stack_name: str,
    service_name: str,
    key: str,
    value: str,
    services: dict[str, ServiceSpec],
    generated_env_file_sources: dict[str, EnvFileSource],
) -> bool:
    spec = services[service_name]
    merged = _merged_service_env(cwd, spec)
    if merged.get(key) == value:
        return False

    target_path = _generated_env_file_path(cwd, stack_name, service_name)
    target_values = dict(read_env_file(target_path))
    target_values[key] = value
    write_env_file(target_path, target_values)

    target_ref = _generated_env_file_ref(stack_name, service_name)
    service_env_file = list(spec.env_file or [])
    if target_ref not in service_env_file:
        service_env_file.append(target_ref)

    existing = generated_env_file_sources.get(service_name)
    added_keys = [
        *(existing.added_keys if existing and existing.added_keys else []),
        key,
    ]
    generated_env_file_sources[service_name] = EnvFileSource(
        generated=True,
        path=target_ref,
        added_keys=sorted(set(added_keys)),
    )
    services[service_name] = spec.model_copy(update={"env_file": service_env_file})
    return True


def _ensure_inline_env(
    *,
    service_name: str,
    key: str,
    value: str,
    services: dict[str, ServiceSpec],
) -> bool:
    spec = services[service_name]
    environment = dict(spec.environment or {})
    if environment.get(key) == value:
        return False
    environment[key] = value
    services[service_name] = spec.model_copy(update={"environment": environment})
    return True


def wire_wordpress_mysql(
    *,
    cwd: str,
    stack_name: str,
    app_name: str,
    db_name: str,
    services: dict[str, ServiceSpec],
    generated_env_file_sources: dict[str, EnvFileSource],
) -> list[tuple[str, list[str]]]:
    """Wire WordPress env to a MySQL/MariaDB dependency. Returns (service, keys) pairs."""
    app_spec = services[app_name]
    db_spec = services[db_name]
    if not WORDPRESS_IMAGE.search(app_spec.image):
        return []

    keys = _mysql_family_keys(db_spec.image, _merged_service_env(cwd, app_spec).get("WORDPRESS_DB_USER", "root"))
    if keys is None:
        return []

    db_password_key, db_database_key = keys
    app_env = _merged_service_env(cwd, app_spec)
    db_env = _merged_service_env(cwd, db_spec)
    wired: list[tuple[str, list[str]]] = []

    db_password = db_env.get(db_password_key)
    if db_password and app_env.get("WORDPRESS_DB_PASSWORD") is None:
        if _ensure_env_file_value(
            cwd=cwd,
            stack_name=stack_name,
            service_name=app_name,
            key="WORDPRESS_DB_PASSWORD",
            value=db_password,
            services=services,
            generated_env_file_sources=generated_env_file_sources,
        ):
            wired.append((app_name, ["WORDPRESS_DB_PASSWORD"]))

    db_name_value = app_env.get("WORDPRESS_DB_NAME", DEFAULT_WORDPRESS_DB_NAME)
    if app_env.get("WORDPRESS_DB_NAME") is None:
        if _ensure_inline_env(
            service_name=app_name,
            key="WORDPRESS_DB_NAME",
            value=db_name_value,
            services=services,
        ):
            wired.append((app_name, ["WORDPRESS_DB_NAME"]))

    if db_env.get(db_database_key) is None:
        if _ensure_env_file_value(
            cwd=cwd,
            stack_name=stack_name,
            service_name=db_name,
            key=db_database_key,
            value=db_name_value,
            services=services,
            generated_env_file_sources=generated_env_file_sources,
        ):
            wired.append((db_name, [db_database_key]))

    return wired


def wire_dependent_app_secrets(
    cwd: str,
    stack_name: str,
    services: dict[str, ServiceSpec],
    generated_env_file_sources: dict[str, EnvFileSource],
) -> list[tuple[str, list[str]]]:
    """Copy generated DB credentials into dependent app services when missing."""
    wired: list[tuple[str, list[str]]] = []

    for app_name, app_spec in services.items():
        db_deps = _db_dependency_names(app_spec, services)
        if not db_deps:
            continue
        db_name = db_deps[0]
        wired.extend(
            wire_wordpress_mysql(
                cwd=cwd,
                stack_name=stack_name,
                app_name=app_name,
                db_name=db_name,
                services=services,
                generated_env_file_sources=generated_env_file_sources,
            )
        )

    return wired


__all__ = ["wire_dependent_app_secrets", "wire_wordpress_mysql"]
