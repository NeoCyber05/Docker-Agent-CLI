"""LoopContext shape smoke test."""

from src.loop_context import PlanReadyPayload
from src.types.stack import StackDiff


def test_plan_ready_payload() -> None:
    payload = PlanReadyPayload(
        compose_yaml="services:",
        diff=StackDiff(stack_name="demo", status="missing", service_diffs=[]),
    )
    assert payload.compose_yaml == "services:"