"""get_health tool.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from docker_mcp_server.services.docker.types import ContainerStats
from docker_mcp_server.tools.base import ToolContext, ToolDone, ToolProgress

CRASH_LOOP_THRESHOLD = 3
_BYTES_PER_MB = 1024 * 1024

_MODEL_CONFIG = ConfigDict(extra="forbid", populate_by_name=True)


@dataclass
class ComputedStats:
    cpu_percent: float | None
    mem_used_mb: float | None
    mem_limit_mb: float | None
    mem_percent: float | None


def compute_stats(raw: ContainerStats) -> ComputedStats:
    """Pure CPU/mem math over a raw docker stats sample."""
    mem = _compute_mem(raw)
    return ComputedStats(
        cpu_percent=_compute_cpu_percent(raw),
        mem_used_mb=mem["mem_used_mb"],
        mem_limit_mb=mem["mem_limit_mb"],
        mem_percent=mem["mem_percent"],
    )


def _compute_cpu_percent(raw: ContainerStats) -> float | None:
    pre = raw.precpu_stats
    if not pre:
        return None
    cpu_stats = raw.cpu_stats or {}
    sys_now = cpu_stats.get("system_cpu_usage")
    sys_pre = pre.get("system_cpu_usage")
    if sys_now is None or sys_pre is None:
        return None
    system_delta = float(sys_now) - float(sys_pre)
    if system_delta <= 0:
        return None
    cpu_usage = cpu_stats.get("cpu_usage") or {}
    pre_cpu_usage = pre.get("cpu_usage") or {}
    cpu_delta = float(cpu_usage.get("total_usage", 0)) - float(
        pre_cpu_usage.get("total_usage", 0)
    )
    percpu = cpu_usage.get("percpu_usage")
    num_cpus_raw = cpu_stats.get("online_cpus")
    num_cpus = (len(percpu) if percpu else 1) if num_cpus_raw is None else int(num_cpus_raw)
    return (cpu_delta / system_delta) * num_cpus * 100


def _compute_mem(raw: ContainerStats) -> dict[str, float | None]:
    memory_stats = raw.memory_stats or {}
    usage = memory_stats.get("usage")
    limit = memory_stats.get("limit")
    if usage is None or limit is None or limit == 0:
        return {"mem_used_mb": None, "mem_limit_mb": None, "mem_percent": None}
    return {
        "mem_used_mb": usage / _BYTES_PER_MB,
        "mem_limit_mb": limit / _BYTES_PER_MB,
        "mem_percent": (usage / limit) * 100,
    }


class GetHealthInput(BaseModel):
    model_config = _MODEL_CONFIG

    stack_name: str = Field(alias="stackName")


class HealthRow(BaseModel):
    model_config = _MODEL_CONFIG

    name: str
    service: str
    status: str
    health: str | None = None
    cpu_percent: float | None = Field(default=None, alias="cpuPercent")
    mem_used_mb: float | None = Field(default=None, alias="memUsedMb")
    mem_limit_mb: float | None = Field(default=None, alias="memLimitMb")
    mem_percent: float | None = Field(default=None, alias="memPercent")
    restart_count: int = Field(alias="restartCount")
    crash_loop: bool = Field(alias="crashLoop")
    error: str | None = None


class GetHealthResult(BaseModel):
    model_config = _MODEL_CONFIG

    containers: list[HealthRow]
    crash_loops: list[str] = Field(alias="crashLoops")
    error: str | None = None


def _err_msg(error: object) -> str:
    return str(error)


def _is_crash_loop(restart_count: int, status: str) -> bool:
    return restart_count >= CRASH_LOOP_THRESHOLD or status == "restarting"


class GetHealthTool:
    name = "get_health"
    description = (
        "Per-container status, health, CPU%, memory, restart count, and "
        "crash-loop flag for a stack (read-only)."
    )
    input_schema = GetHealthInput
    category = "read-only"

    def needs_permission(self, _input: GetHealthInput) -> bool:
        return False

    async def call(
        self, input: GetHealthInput, ctx: ToolContext
    ) -> AsyncIterator[ToolProgress | ToolDone]:
        yield ToolProgress(msg=f"Inspecting health for {input.stack_name}...")
        engine = ctx.docker_engine

        try:
            summaries = await engine.list_containers(
                all=True,
                filters={"label": [f"com.docker.compose.project={input.stack_name}"]},
            )
        except Exception as error:
            yield ToolDone(
                GetHealthResult(
                    containers=[],
                    crashLoops=[],
                    error=_err_msg(error),
                )
            )
            return

        containers: list[HealthRow] = []
        for summary in summaries:
            name = summary.names[0] if summary.names else summary.id
            service = summary.labels.get("com.docker.compose.service", "")
            status = summary.state
            health: str | None = None
            restart_count = 0
            cpu_percent: float | None = None
            mem_used_mb: float | None = None
            mem_limit_mb: float | None = None
            mem_percent: float | None = None
            row_error: str | None = None

            try:
                inspected = await engine.inspect(summary.id)
                status = inspected.state.status
                if inspected.state.health is not None:
                    health = inspected.state.health.status
                restart_count = inspected.restart_count
            except Exception as inspect_error:
                row_error = _err_msg(inspect_error)

            try:
                raw_stats: ContainerStats = await engine.stats(summary.id)
                computed = compute_stats(raw_stats)
                cpu_percent = computed.cpu_percent
                mem_used_mb = computed.mem_used_mb
                mem_limit_mb = computed.mem_limit_mb
                mem_percent = computed.mem_percent
            except Exception as stats_error:
                stats_msg = _err_msg(stats_error)
                row_error = f"{row_error}; {stats_msg}" if row_error else stats_msg

            row_data: dict[str, Any] = {
                "name": name,
                "service": service,
                "status": status,
                "cpuPercent": cpu_percent,
                "memUsedMb": mem_used_mb,
                "memLimitMb": mem_limit_mb,
                "memPercent": mem_percent,
                "restartCount": restart_count,
                "crashLoop": _is_crash_loop(restart_count, status),
            }
            if health is not None:
                row_data["health"] = health
            if row_error is not None:
                row_data["error"] = row_error
            containers.append(HealthRow.model_validate(row_data))

        crash_loops = [row.name for row in containers if row.crash_loop]
        yield ToolDone(GetHealthResult(containers=containers, crashLoops=crash_loops))


get_health = GetHealthTool()

__all__ = [
    "CRASH_LOOP_THRESHOLD",
    "ComputedStats",
    "GetHealthInput",
    "GetHealthResult",
    "GetHealthTool",
    "HealthRow",
    "compute_stats",
    "get_health",
]
