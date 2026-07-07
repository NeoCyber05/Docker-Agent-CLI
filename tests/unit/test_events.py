from __future__ import annotations

from pydantic import TypeAdapter

from infra_agent.types.events import ActionReview, LoopEvent

_LoopEventAdapter: TypeAdapter[LoopEvent] = TypeAdapter(LoopEvent)


def test_action_review_event_is_plugin_neutral() -> None:
    ev = _LoopEventAdapter.validate_python(
        {
            "type": "action_review",
            "id": "req-1",
            "pendingActionId": "pending-1",
            "tool": "k8s.deploy",
            "title": "Review Kubernetes deployment",
            "summary": "Create deployment web.",
            "artifacts": [
                {
                    "kind": "manifest",
                    "label": "Deployment",
                    "language": "yaml",
                    "content": "kind: Deployment\n",
                }
            ],
            "warnings": ["Cluster context: dev"],
        }
    )

    assert isinstance(ev, ActionReview)
    assert ev.pending_action_id == "pending-1"
    assert ev.artifacts[0].kind == "manifest"


def test_action_review_event_allows_docker_as_artifact_not_schema() -> None:
    ev = _LoopEventAdapter.validate_python(
        {
            "type": "action_review",
            "id": "req-2",
            "pendingActionId": "pending-docker",
            "tool": "docker.deploy_stack",
            "title": "Review docker.deploy_stack",
            "summary": "Review generated Docker Compose changes.",
            "artifacts": [
                {
                    "kind": "compose",
                    "label": "Compose YAML",
                    "language": "yaml",
                    "content": "services: {}",
                },
                {
                    "kind": "diff",
                    "label": "Resource diff",
                    "content": {"stackName": "web", "serviceDiffs": []},
                },
            ],
        }
    )

    assert isinstance(ev, ActionReview)
    assert ev.artifacts[0].content == "services: {}"
    assert ev.artifacts[1].content == {"stackName": "web", "serviceDiffs": []}

