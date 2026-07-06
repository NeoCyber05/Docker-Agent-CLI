"""Default database healthchecks and depends_on upgrades.

Parity: ``src/tools/shared/dbHealthcheck.ts``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from docker_mcp_server.types.stack import HealthcheckSpec, ServiceSpec

DependsOnConditionName = Literal[
    "service_started", "service_healthy", "service_completed_successfully"
]


@dataclass(frozen=True)
class DefaultHealthcheck:
    image_pattern: re.Pattern[str]
    healthcheck: HealthcheckSpec


DEFAULT_DB_HEALTHCHECKS: list[DefaultHealthcheck] = [
    DefaultHealthcheck(
        image_pattern=re.compile(r"^postgres(:|$)"),
        healthcheck=HealthcheckSpec.model_validate(
            {
                "test": ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres}"],
                "interval": "10s",
                "timeout": "5s",
                "retries": 5,
                "start_period": "30s",
            }
        ),
    ),
    DefaultHealthcheck(
        image_pattern=re.compile(r"^mysql(:|$)"),
        healthcheck=HealthcheckSpec.model_validate(
            {
                "test": ["CMD", "mysqladmin", "ping", "-h", "localhost"],
                "interval": "10s",
                "timeout": "5s",
                "retries": 5,
                "start_period": "30s",
            }
        ),
    ),
    DefaultHealthcheck(
        image_pattern=re.compile(r"^mariadb(:|$)"),
        healthcheck=HealthcheckSpec.model_validate(
            {
                "test": ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"],
                "interval": "10s",
                "timeout": "5s",
                "retries": 5,
                "start_period": "30s",
            }
        ),
    ),
    DefaultHealthcheck(
        image_pattern=re.compile(r"^mongo(:|$)"),
        healthcheck=HealthcheckSpec.model_validate(
            {
                "test": ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"],
                "interval": "10s",
                "timeout": "5s",
                "retries": 5,
                "start_period": "30s",
            }
        ),
    ),
    DefaultHealthcheck(
        image_pattern=re.compile(r"^redis(:|$)"),
        healthcheck=HealthcheckSpec.model_validate(
            {
                "test": ["CMD", "redis-cli", "ping"],
                "interval": "10s",
                "timeout": "3s",
                "retries": 5,
                "start_period": "5s",
            }
        ),
    ),
]


def inject_db_healthchecks(
    services: dict[str, ServiceSpec],
) -> dict[str, int]:
    """Inject healthchecks for DB images and upgrade depends_on conditions."""
    injected_count = 0
    updated_deps_count = 0
    db_services: set[str] = set()

    for name, spec in services.items():
        rule = next(
            (r for r in DEFAULT_DB_HEALTHCHECKS if r.image_pattern.search(spec.image)),
            None,
        )
        if rule is not None:
            db_services.add(name)
            if spec.healthcheck is None:
                spec.healthcheck = rule.healthcheck.model_copy(deep=True)
                injected_count += 1

    for _name, spec in services.items():
        if spec.depends_on is None:
            continue

        if isinstance(spec.depends_on, list):
            new_depends_on: dict[str, dict[str, DependsOnConditionName]] = {}
            changed = False
            for dep in spec.depends_on:
                if dep in db_services:
                    new_depends_on[dep] = {"condition": "service_healthy"}
                    changed = True
                else:
                    new_depends_on[dep] = {"condition": "service_started"}
            if changed:
                spec.depends_on = new_depends_on
                updated_deps_count += 1
        elif isinstance(spec.depends_on, dict):
            changed = False
            new_depends_on = dict(spec.depends_on)
            for dep in list(new_depends_on.keys()):
                if dep not in db_services:
                    continue
                current_dep = new_depends_on[dep]
                if (
                    isinstance(current_dep, dict)
                    and current_dep.get("condition") != "service_healthy"
                    and current_dep.get("condition") != "service_completed_successfully"
                ):
                    new_depends_on[dep] = {**current_dep, "condition": "service_healthy"}
                    changed = True
            if changed:
                spec.depends_on = new_depends_on
                updated_deps_count += 1

    return {"injected_count": injected_count, "updated_deps_count": updated_deps_count}


__all__ = [
    "DEFAULT_DB_HEALTHCHECKS",
    "DefaultHealthcheck",
    "inject_db_healthchecks",
]
