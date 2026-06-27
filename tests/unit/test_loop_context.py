"""LoopContext shape smoke test."""

from docker_agent.loop_context import PlanReadyPayload
from docker_agent.types.stack import StackDiff


def test_plan_ready_payload() -> None:
    payload = PlanReadyPayload(
        compose_yaml="services:",
        diff=StackDiff(stack_name="demo", status="missing", service_diffs=[]),
    )
    assert payload.compose_yaml == "services:"