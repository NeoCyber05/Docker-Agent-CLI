"""Graph wiring tests."""

from __future__ import annotations

from src.engine.graph import GraphDeps, build_graph
from src.policy.policy_engine import PolicyEngine


def test_build_graph_compiles(make_loop_ctx, tmp_project) -> None:
    ctx = make_loop_ctx()
    policy = PolicyEngine(project_policy_path=str(tmp_project / "project-policies.yaml"))
    (tmp_project / "project-policies.yaml").write_text("project: {}\n", encoding="utf-8")

    class FakeProvider:
        name = "fake"

        async def stream(self, _params):
            return
            yield  # pragma: no cover

    graph = build_graph(
        GraphDeps(
            provider=FakeProvider(),
            ctx=ctx,
            model=None,
            emit=lambda _x: None,
            policy_engine=policy,
        )
    )
    assert graph is not None