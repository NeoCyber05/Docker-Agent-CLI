"""Query engine helpers (partial — CurrentBackend is Plan 08).

Parity: ``src/query.ts``.
"""

from __future__ import annotations

from docker_agent.tools.plan_stack import PlanStackResultBlocked


def format_plan_blocker(result: PlanStackResultBlocked) -> str:
    """Format a blocked plan_stack result into a user-facing message."""
    reason = result.reason
    if reason == "invalid_spec":
        issues = result.issues or []
        body = "\n".join(f"- [{i.path}] {i.message}" for i in issues)
        return f"plan_stack blocked: Specification is invalid:\n{body}"
    if reason == "invalid_dependency":
        dep = result.dependency
        lines = ["plan_stack blocked: Invalid dependency order."]
        if dep is not None:
            for m in dep.missing:
                lines.append(
                    f"- Service '{m.service}' depends on missing service '{m.dependency}'."
                )
            for cycle in dep.cycles:
                lines.append(f"- Circular dependency detected: {' -> '.join(cycle)}.")
        return "\n".join(lines)
    if reason == "port_conflict":
        pc = result.port_check
        lines = ["plan_stack blocked: Port conflict detected."]
        if pc is not None:
            for conflict in pc.conflicts:
                source = (
                    "running container"
                    if conflict.source == "running"
                    else "other service"
                )
                lines.append(
                    f"- Port {conflict.host_port}/{conflict.protocol} published by service "
                    f"'{conflict.service}' conflicts with {conflict.conflicts_with} ({source})."
                )
            for inv in pc.invalid:
                lines.append(
                    f"- Service '{inv['service']}' has invalid port mapping "
                    f"'{inv['value']}': {inv['message']}"
                )
            if pc.docker_error:
                lines.append(f"- Docker Engine error: {pc.docker_error['message']}")
        return "\n".join(lines)
    if reason == "missing_config_file":
        paths = result.missing_files or []
        return (
            f"plan_stack blocked: Missing content for config file(s): {', '.join(paths)}."
        )
    if reason == "missing_required_env":
        lines = ["plan_stack blocked: Missing required environment variables."]
        for svc, keys in (result.missing_by_service or {}).items():
            lines.append(f"- Service '{svc}' requires: {', '.join(keys)}")
        return "\n".join(lines)
    if reason == "resource_limit":
        resource_issues = result.resource_issues or []
        body = "\n".join(f"- [{i.path}] {i.message}" for i in resource_issues)
        return f"plan_stack blocked: Resource limit exceeded:\n{body}"
    if reason == "db_port_exposed":
        db_issues = result.db_port_issues or []
        body = "\n".join(f"- [{i.service}] {i.message}" for i in db_issues)
        return f"plan_stack blocked: Database port publicly exposed:\n{body}"
    if reason == "unsafe_volume":
        volume_issues = result.volume_issues or []
        body = "\n".join(f"- [{i.service}] {i.message}" for i in volume_issues)
        return f"plan_stack blocked: Unsafe volume mount detected:\n{body}"
    if reason == "undeclared_network":
        network_issues = result.network_issues or []
        body = "\n".join(f"- [{i.service}] {i.message}" for i in network_issues)
        return f"plan_stack blocked: Undeclared network reference:\n{body}"
    if reason == "invalid_yaml":
        return f"plan_stack blocked: {result.error}"
    return f"plan_stack blocked: {reason}"


__all__ = ["format_plan_blocker"]