from __future__ import annotations

from docker_agent.core.prompt_builder import build_system_prompt


def test_prompt_describes_deploy_stack_as_primary_deploy_tool() -> None:
    prompt = build_system_prompt("stacks: {}\n")

    assert "Every deployment or stack change MUST go through `docker.deploy_stack`" in prompt
    assert "server-side `plan_stack` gate" in prompt
    assert "Do NOT invoke `plan_stack`" in prompt
    assert "use `docker.validate_spec` only as an optional diagnostic" in prompt
    assert "same full draft preflight" in prompt
    assert "dependency order" in prompt
    assert "Preflight report artifact" in prompt
    assert "required workflow preflight" not in prompt
    assert "Before `plan_stack`:" not in prompt
    assert "Call `plan_stack` only" not in prompt