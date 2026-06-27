from docker_agent.backend.langgraph.state import AgentState


def test_agent_state_defaults() -> None:
    state = AgentState(messages=[], iter=0, allow_set=set(), pending_tool_results=[], aborted=False)
    assert state.iter == 0
    assert not state.aborted