from __future__ import annotations

from infra_agent.core.loop_context import ActionReviewPayload


def test_action_review_payload_accepts_plugin_neutral_artifacts() -> None:
    payload = ActionReviewPayload(
        pending_action_id="pending-1",
        tool="k8s.deploy",
        title="Review Kubernetes deployment",
        summary="Create namespace demo and deployment web.",
        artifacts=[
            {
                "kind": "manifest",
                "label": "Kubernetes manifest",
                "language": "yaml",
                "content": "apiVersion: apps/v1\nkind: Deployment\n",
            }
        ],
        warnings=["Cluster context: dev"],
        secrets=[{"name": "DB_PASSWORD", "required": True}],
        config_files=[{"path": "k8s/web.yaml", "bytes": 42}],
    )

    assert payload.pending_action_id == "pending-1"
    assert payload.tool == "k8s.deploy"
    assert payload.artifacts[0].kind == "manifest"
    assert payload.model_dump(by_alias=True)["pendingActionId"] == "pending-1"


def test_action_review_payload_reads_display_artifacts() -> None:
    payload = ActionReviewPayload.from_pending_action_display(
        pending_action_id="pending-docker",
        tool="docker.deploy_stack",
        display={
            "artifacts": [
                {
                    "kind": "manifest",
                    "label": "Compose YAML",
                    "language": "yaml",
                    "content": "services:\n  web:\n    image: nginx\n",
                },
                {
                    "kind": "diff",
                    "label": "Stack diff",
                    "content": {"stackName": "web", "status": "missing", "serviceDiffs": []},
                },
            ],
            "auto_generated_secrets": [{"service": "db", "keys": ["POSTGRES_PASSWORD"]}],
            "config_files": [{"path": "nginx.conf", "bytes": 12}],
        },
    )

    assert payload.title == "Review docker.deploy_stack"
    assert [artifact.kind for artifact in payload.artifacts] == ["manifest", "diff"]
    assert payload.artifacts[0].content.startswith("services:")
    assert payload.secrets == [{"service": "db", "keys": ["POSTGRES_PASSWORD"]}]
    assert payload.config_files == [{"path": "nginx.conf", "bytes": 12}]

