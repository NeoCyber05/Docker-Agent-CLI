"""Parity tests for secret_keys â€” mirrors src/tools/shared/__tests__/secretKeys.test.ts."""

from pathlib import Path

from docker_mcp_server.state.state_store import StateStore
from docker_mcp_server.tools.shared.secret_keys import SecretKeysContext, collect_secret_keys
from docker_mcp_server.types.stack import (
    DockerAgentMeta,
    EnvFileSource,
    ServiceSpec,
    StackDefinition,
)


def test_collect_secret_keys_merges_sources(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    secrets_dir = tmp_path / ".docker-agent" / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "web-web.env").write_text(
        "JWT_TOKEN=abc\nDB_PASSWORD=secret\nDEBUG=true\n",
        encoding="utf-8",
    )

    store.write(
        "web",
        StackDefinition(
            x_infra_agent=DockerAgentMeta(
                name="web",
                created_at="x",
                last_applied=None,
                intent="x",
                provider="x",
                generated_by="x",
                env_file_sources={
                    "web": EnvFileSource(
                        generated=True, path="x", added_keys=["API_KEY"]
                    )
                },
            ),
            services={
                "web": ServiceSpec(
                    image="nginx",
                    environment={"DB_PASSWORD": "secret", "PORT": "8080"},
                    env_file=["./.docker-agent/secrets/web-web.env"],
                )
            },
        ),
    )

    result = collect_secret_keys(
        "web", SecretKeysContext(cwd=str(tmp_path), state_store=store)
    )
    assert sorted(result) == ["API_KEY", "DB_PASSWORD", "JWT_TOKEN"]
    assert "PORT" not in result
    assert "DEBUG" not in result


def test_collect_secret_keys_returns_empty_set_for_unknown_stack(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / ".docker-agent"))
    result = collect_secret_keys(
        "ghost", SecretKeysContext(cwd=str(tmp_path), state_store=store)
    )
    assert len(result) == 0


