from __future__ import annotations

from docker_agent.components.plan_preview import compose_yaml_for_preview, render_plan_preview
from docker_agent.types.stack import FieldChange, ServiceDiff, ServiceSnapshot, StackDiff


def _sample_diff() -> StackDiff:
    return StackDiff(
        stackName="demo",
        status="drift",
        serviceDiffs=[
            ServiceDiff(
                service="web",
                desired=ServiceSnapshot(
                    image="nginx:latest",
                    ports=["80:80"],
                    env={"visible": {}, "secretKeys": [], "secretHashesByKey": {}},
                    volumes=[],
                    replicaCount=1,
                ),
                actual=None,
                changes=[FieldChange(field="image", **{"from": None, "to": "nginx:latest"})],
            )
        ],
    )


def test_compose_yaml_for_preview_strips_metadata() -> None:
    raw = "x-docker-agent: {}\nservices:\n  web:\n    image: nginx"
    preview = compose_yaml_for_preview(raw)
    assert "x-docker-agent" not in preview
    assert "nginx" in preview


def test_render_plan_preview_shows_service_diffs() -> None:
    rendered = render_plan_preview(
        compose_yaml="services:\n  web:\n    image: nginx",
        diff=_sample_diff(),
        status="pending",
    )
    text = str(rendered)
    assert "web" in text
    assert "Apply this plan?" in text


def test_render_plan_preview_shows_bordered_yaml_when_expanded() -> None:
    rendered = render_plan_preview(
        compose_yaml="services:\n  web:\n    image: nginx",
        diff=_sample_diff(),
        show_yaml=True,
        status="pending",
    )
    text = str(rendered)
    assert "┌" in text
    assert "│" in text
    assert "└" in text
    assert "image: nginx" in text


def test_render_plan_preview_shows_decision_status() -> None:
    approved = str(
        render_plan_preview(
            compose_yaml="services:\n  web:\n    image: nginx",
            diff=_sample_diff(),
            status="approved",
        )
    )
    denied = str(
        render_plan_preview(
            compose_yaml="services:\n  web:\n    image: nginx",
            diff=_sample_diff(),
            status="denied",
        )
    )
    assert "Plan approved" in approved
    assert "Plan declined" in denied


def test_render_plan_preview_no_changes_detected() -> None:
    empty_diff = StackDiff(
        stackName="demo",
        status="missing",
        serviceDiffs=[],
    )
    rendered = render_plan_preview(
        compose_yaml="services:\n  web:\n    image: nginx",
        diff=empty_diff,
        status="pending",
    )
    text = str(rendered)
    assert "No changes detected" in text
    assert "No changes detected\nYAML Configuration" in text
