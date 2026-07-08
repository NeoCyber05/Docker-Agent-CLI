"""Wire auto-generated database secrets into dependent application services."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from docker_mcp_server.state.env_file import merge_env, read_env_file
from docker_mcp_server.tools.shared.db_healthcheck import DEFAULT_DB_HEALTHCHECKS
from docker_mcp_server.tools.shared.secret_staging import SecretFileStager
from docker_mcp_server.types.stack import EnvFileSource, ServiceSpec

WORDPRESS_IMAGE = re.compile(r"^wordpress(:|$)")
MONGO_IMAGE = re.compile(r"^mongo(:|$)")
DEFAULT_WORDPRESS_DB_NAME = "wordpress"

GENERIC_DB_URI_KEYS: dict[re.Pattern[str], tuple[str, ...]] = {
    MONGO_IMAGE: ("MONGO_URI", "MONGODB_URI", "DATABASE_URL"),
}


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
    if depends_on is not None:
        dep_names = depends_on if isinstance(depends_on, list) else list(depends_on.keys())
        return [name for name in dep_names if name in services and _is_db_image(services[name].image)]

    inferred = _infer_db_dependency_name(spec, services)
    return [inferred] if inferred else []


def _parse_db_host_service(host: str | None) -> str | None:
    if not host:
        return None
    candidate = host.split(":")[0].strip()
    return candidate or None


def _infer_db_dependency_name(
    spec: ServiceSpec,
    services: dict[str, ServiceSpec],
) -> str | None:
    """Infer a DB dependency when the agent omitted dependsOn but env hints at one."""
    if WORDPRESS_IMAGE.search(spec.image):
        app_env = spec.environment or {}
        host_name = _parse_db_host_service(app_env.get("WORDPRESS_DB_HOST"))
        if host_name and host_name in services and _is_db_image(services[host_name].image):
            return host_name

    db_services = [
        name for name, candidate in services.items() if _is_db_image(candidate.image)
    ]
    if WORDPRESS_IMAGE.search(spec.image) and len(db_services) == 1:
        return db_services[0]
    return None


def infer_implicit_db_dependencies(services: dict[str, ServiceSpec]) -> int:
    """Add depends_on for app services that reference a DB via env but omitted dependsOn."""
    updated = 0
    for spec in services.values():
        if spec.depends_on is not None:
            continue
        db_name = _infer_db_dependency_name(spec, services)
        if db_name is None:
            continue
        spec.depends_on = [db_name]
        updated += 1
    return updated


@dataclass
class DbAppWiringIssue:
    service: str
    path: str
    message: str


def _env_value_set(value: str | None) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _wordpress_app_db_user(app_env: dict[str, str]) -> str:
    return (app_env.get("WORDPRESS_DB_USER") or "root").strip() or "root"


def _mysql_family_user_password_keys(db_image: str) -> tuple[str, str] | None:
    if re.search(r"^mysql(:|$)", db_image):
        return "MYSQL_USER", "MYSQL_PASSWORD"
    if re.search(r"^mariadb(:|$)", db_image):
        return "MARIADB_USER", "MARIADB_PASSWORD"
    return None


def _merged_service_env(
    cwd: str,
    spec: ServiceSpec,
    stager: SecretFileStager | None = None,
) -> dict[str, str]:
    from_env_file: dict[str, str] = {}
    for env_file_path in spec.env_file or []:
        resolved = _resolve_env_file(cwd, env_file_path)
        if stager is not None:
            from_env_file.update(stager.read(resolved))
        else:
            from_env_file.update(read_env_file(resolved))
    return merge_env(from_env_file, spec.environment or {})


def _mysql_family_keys(db_image: str, app_db_user: str) -> tuple[str, str] | None:
    if re.search(r"^mysql(:|$)", db_image):
        password_key = (
            "MYSQL_ROOT_PASSWORD"
            if app_db_user.lower() == "root"
            else "MYSQL_PASSWORD"
        )
        return password_key, "MYSQL_DATABASE"
    if re.search(r"^mariadb(:|$)", db_image):
        password_key = (
            "MARIADB_ROOT_PASSWORD"
            if app_db_user.lower() == "root"
            else "MARIADB_PASSWORD"
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
    stager: SecretFileStager,
) -> bool:
    spec = services[service_name]
    merged = _merged_service_env(cwd, spec, stager)
    if merged.get(key) == value:
        return False

    target_path = _generated_env_file_path(cwd, stack_name, service_name)
    stager.stage(target_path, {**stager.read(target_path), key: value})

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


def _ensure_mysql_app_user_for_wordpress(
    *,
    cwd: str,
    stack_name: str,
    app_name: str,
    db_name: str,
    services: dict[str, ServiceSpec],
    generated_env_file_sources: dict[str, EnvFileSource],
    stager: SecretFileStager,
) -> list[tuple[str, list[str]]]:
    """Create a matching MySQL/MariaDB app user when WordPress requests a non-root user."""
    app_spec = services[app_name]
    db_spec = services[db_name]
    user_keys = _mysql_family_user_password_keys(db_spec.image)
    if user_keys is None:
        return []

    user_key, password_key = user_keys
    app_env = _merged_service_env(cwd, app_spec, stager)
    app_db_user = _wordpress_app_db_user(app_env)
    if app_db_user.lower() == "root":
        return []

    db_env = _merged_service_env(cwd, db_spec, stager)
    wired: list[tuple[str, list[str]]] = []

    existing_user = db_env.get(user_key)
    if not _env_value_set(existing_user):
        if _ensure_inline_env(
            service_name=db_name,
            key=user_key,
            value=app_db_user,
            services=services,
        ):
            wired.append((db_name, [user_key]))
    elif existing_user.strip() != app_db_user:
        return wired

    db_env = _merged_service_env(cwd, services[db_name], stager)
    if not _env_value_set(db_env.get(password_key)):
        generated = secrets.token_urlsafe(24)
        if _ensure_env_file_value(
            cwd=cwd,
            stack_name=stack_name,
            service_name=db_name,
            key=password_key,
            value=generated,
            services=services,
            generated_env_file_sources=generated_env_file_sources,
            stager=stager,
        ):
            wired.append((db_name, [password_key]))

    return wired


def check_db_app_credential_consistency(
    services: dict[str, ServiceSpec],
) -> list[DbAppWiringIssue]:
    """Detect WordPress DB user names that conflict with an explicit database user."""
    issues: list[DbAppWiringIssue] = []
    for app_name, app_spec in services.items():
        if not WORDPRESS_IMAGE.search(app_spec.image):
            continue
        db_deps = _db_dependency_names(app_spec, services)
        if not db_deps:
            continue
        db_spec = services[db_deps[0]]
        user_keys = _mysql_family_user_password_keys(db_spec.image)
        if user_keys is None:
            continue

        user_key, _ = user_keys
        app_env = app_spec.environment or {}
        app_user = _wordpress_app_db_user(app_env)
        if app_user.lower() == "root":
            continue

        db_user = (db_spec.environment or {}).get(user_key)
        if db_user and db_user.strip() and db_user.strip() != app_user:
            issues.append(
                DbAppWiringIssue(
                    service=app_name,
                    path=f"services.{app_name}.environment.WORDPRESS_DB_USER",
                    message=(
                        f"WordPress user '{app_user}' does not match "
                        f"{user_key}='{db_user.strip()}' on service '{db_deps[0]}'."
                    ),
                )
            )
    return issues


def check_db_app_credentials_resolved(
    cwd: str,
    services: dict[str, ServiceSpec],
    stager: SecretFileStager,
) -> list[DbAppWiringIssue]:
    """Fail when a non-root WordPress user still has no wired database password."""
    issues: list[DbAppWiringIssue] = []
    for app_name, app_spec in services.items():
        if not WORDPRESS_IMAGE.search(app_spec.image):
            continue
        db_deps = _db_dependency_names(app_spec, services)
        if not db_deps:
            continue
        db_spec = services[db_deps[0]]
        if _mysql_family_user_password_keys(db_spec.image) is None:
            continue

        app_env = _merged_service_env(cwd, app_spec, stager)
        app_user = _wordpress_app_db_user(app_env)
        if app_user.lower() == "root":
            continue
        if _env_value_set(app_env.get("WORDPRESS_DB_PASSWORD")):
            continue

        issues.append(
            DbAppWiringIssue(
                service=app_name,
                path=f"services.{app_name}.environment.WORDPRESS_DB_PASSWORD",
                message=(
                    f"Could not wire a database password for WordPress user "
                    f"'{app_user}' from service '{db_deps[0]}'."
                ),
            )
        )
    return issues


def wire_wordpress_mysql(
    *,
    cwd: str,
    stack_name: str,
    app_name: str,
    db_name: str,
    services: dict[str, ServiceSpec],
    generated_env_file_sources: dict[str, EnvFileSource],
    stager: SecretFileStager,
) -> list[tuple[str, list[str]]]:
    """Wire WordPress env to a MySQL/MariaDB dependency. Returns (service, keys) pairs."""
    app_spec = services[app_name]
    db_spec = services[db_name]
    if not WORDPRESS_IMAGE.search(app_spec.image):
        return []

    wired: list[tuple[str, list[str]]] = []
    wired.extend(
        _ensure_mysql_app_user_for_wordpress(
            cwd=cwd,
            stack_name=stack_name,
            app_name=app_name,
            db_name=db_name,
            services=services,
            generated_env_file_sources=generated_env_file_sources,
            stager=stager,
        )
    )

    app_env = _merged_service_env(cwd, services[app_name], stager)
    keys = _mysql_family_keys(db_spec.image, _wordpress_app_db_user(app_env))
    if keys is None:
        return wired

    db_password_key, db_database_key = keys
    db_env = _merged_service_env(cwd, services[db_name], stager)

    db_password = db_env.get(db_password_key)
    if (
        db_password
        and app_env.get("WORDPRESS_DB_PASSWORD") in (None, "")
        and _ensure_env_file_value(
            cwd=cwd,
            stack_name=stack_name,
            service_name=app_name,
            key="WORDPRESS_DB_PASSWORD",
            value=db_password,
            services=services,
            generated_env_file_sources=generated_env_file_sources,
            stager=stager,
        )
    ):
        wired.append((app_name, ["WORDPRESS_DB_PASSWORD"]))

    db_name_value = app_env.get("WORDPRESS_DB_NAME", DEFAULT_WORDPRESS_DB_NAME)
    if app_env.get("WORDPRESS_DB_NAME") is None and _ensure_inline_env(
        service_name=app_name,
        key="WORDPRESS_DB_NAME",
        value=db_name_value,
        services=services,
    ):
        wired.append((app_name, ["WORDPRESS_DB_NAME"]))

    if (
        db_env.get(db_database_key) is None
        and _ensure_env_file_value(
            cwd=cwd,
            stack_name=stack_name,
            service_name=db_name,
            key=db_database_key,
            value=db_name_value,
            services=services,
            generated_env_file_sources=generated_env_file_sources,
            stager=stager,
        )
    ):
        wired.append((db_name, [db_database_key]))

    return wired


def _mongo_connection_string(
    db_env: dict[str, str], *, db_name: str, db_host: str
) -> str | None:
    password = db_env.get("MONGO_INITDB_ROOT_PASSWORD")
    if not password:
        return None
    user = db_env.get("MONGO_INITDB_ROOT_USERNAME", "root")
    return f"mongodb://{user}:{password}@{db_host}:27017/{db_name}?authSource=admin"


def wire_generic_db_uri(
    *,
    cwd: str,
    stack_name: str,
    app_name: str,
    db_name: str,
    services: dict[str, ServiceSpec],
    generated_env_file_sources: dict[str, EnvFileSource],
    stager: SecretFileStager,
) -> list[tuple[str, list[str]]]:
    """Wire Mongo (and future DB families) URI env vars from staged DB credentials."""
    app_spec = services[app_name]
    db_spec = services[db_name]
    if WORDPRESS_IMAGE.search(app_spec.image):
        return []

    candidate_keys = next(
        (
            keys
            for pattern, keys in GENERIC_DB_URI_KEYS.items()
            if pattern.search(db_spec.image)
        ),
        (),
    )
    if not candidate_keys:
        return []

    app_env = _merged_service_env(cwd, app_spec, stager)
    present_key = next((key for key in candidate_keys if key in app_env), None)
    if present_key is None:
        return []

    db_env = _merged_service_env(cwd, db_spec, stager)
    uri = _mongo_connection_string(db_env, db_name=db_name, db_host=db_name)
    if uri is None or app_env.get(present_key) == uri:
        return []

    if _ensure_env_file_value(
        cwd=cwd,
        stack_name=stack_name,
        service_name=app_name,
        key=present_key,
        value=uri,
        services=services,
        generated_env_file_sources=generated_env_file_sources,
        stager=stager,
    ):
        return [(app_name, [present_key])]
    return []


def wire_dependent_app_secrets(
    cwd: str,
    stack_name: str,
    services: dict[str, ServiceSpec],
    generated_env_file_sources: dict[str, EnvFileSource],
    stager: SecretFileStager,
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
                stager=stager,
            )
        )
        wired.extend(
            wire_generic_db_uri(
                cwd=cwd,
                stack_name=stack_name,
                app_name=app_name,
                db_name=db_name,
                services=services,
                generated_env_file_sources=generated_env_file_sources,
                stager=stager,
            )
        )

    return wired


__all__ = [
    "DbAppWiringIssue",
    "check_db_app_credential_consistency",
    "check_db_app_credentials_resolved",
    "infer_implicit_db_dependencies",
    "wire_dependent_app_secrets",
    "wire_generic_db_uri",
    "wire_wordpress_mysql",
]

