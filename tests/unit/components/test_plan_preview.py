from __future__ import annotations

from docker_agent.components.plan_preview import render_action_review_preview
from docker_agent.ui.activity import ActionReviewArtifactRef


def _sample_artifacts() -> list[ActionReviewArtifactRef]:
    return [
        ActionReviewArtifactRef(
            kind="manifest",
            label="Kubernetes manifest",
            language="yaml",
            content="apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: web",
        ),
        ActionReviewArtifactRef(
            kind="diff",
            label="Resource diff",
            content={"resource": "deployment/web", "status": "missing"},
        ),
    ]


def test_render_action_review_preview_shows_artifact_labels() -> None:
    rendered = render_action_review_preview(
        tool="k8s.deploy",
        title="Deploy workload",
        summary="Create deployment/web",
        artifacts=_sample_artifacts(),
        status="pending",
    )
    text = str(rendered)
    assert "Deploy workload" in text
    assert "k8s.deploy" in text
    assert "Kubernetes manifest" in text
    assert "Approve this action?" in text


def test_render_action_review_preview_shows_bordered_artifacts_when_expanded() -> None:
    rendered = render_action_review_preview(
        tool="k8s.deploy",
        title="Deploy workload",
        summary="Create deployment/web",
        artifacts=_sample_artifacts(),
        show_artifacts=True,
        status="pending",
    )
    text = str(rendered)
    assert "+" in text
    assert "|" in text
    assert "kind: Deployment" in text
    assert "deployment/web" in text


def test_render_action_review_preview_shows_decision_status() -> None:
    approved = str(
        render_action_review_preview(
            tool="k8s.deploy",
            title="Deploy workload",
            summary="Create deployment/web",
            artifacts=_sample_artifacts(),
            status="approved",
        )
    )
    denied = str(
        render_action_review_preview(
            tool="k8s.deploy",
            title="Deploy workload",
            summary="Create deployment/web",
            artifacts=_sample_artifacts(),
            status="denied",
        )
    )
    assert "Action approved" in approved
    assert "Action declined" in denied


def test_render_action_review_preview_allows_no_artifacts() -> None:
    rendered = render_action_review_preview(
        tool="aws.deploy",
        title="Deploy service",
        summary="No manifest artifact returned.",
        artifacts=[],
        status="pending",
    )
    text = str(rendered)
    assert "Deploy service" in text
    assert "Artifacts" not in text