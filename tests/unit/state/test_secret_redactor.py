"""Parity tests for secret_redactor â€” mirrors src/state/secretRedactor.ts."""

import re

from infra_agent.state.secret_redactor import (
    SECRET_KEY_PATTERN,
    hash_secret,
    redact_env,
    scrub_line,
    should_redact,
)

# --- should_redact ------------------------------------------------------

def test_should_match_common_secret_keys() -> None:
    assert should_redact("POSTGRES_PASSWORD")
    assert should_redact("API_KEY")
    assert should_redact("api-key")
    assert should_redact("SECRET_TOKEN")
    assert should_redact("auth")


def test_should_not_match_non_secret_keys() -> None:
    assert not should_redact("DATABASE_URL")
    assert not should_redact("NODE_ENV")


def test_should_not_match_partial_word_false_positives() -> None:
    assert not should_redact("SECRETARY")
    assert not should_redact("TOKENIZE")
    assert not should_redact("AUTHENTIC")
    assert not should_redact("PASSWORD_MANAGER")


def test_regex_has_expected_structure() -> None:
    assert SECRET_KEY_PATTERN.flags & re.IGNORECASE
    assert "api[_-]?key" in SECRET_KEY_PATTERN.pattern


# --- hash_secret --------------------------------------------------------

def test_hash_secret_is_deterministic() -> None:
    assert hash_secret("hunter2", "salt") == hash_secret("hunter2", "salt")


def test_hash_secret_salt_changes_output() -> None:
    assert hash_secret("hunter2", "salt1") != hash_secret("hunter2", "salt2")


def test_hash_secret_is_64_hex_chars() -> None:
    digest = hash_secret("x", "y")
    assert len(digest) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


# --- redact_env ---------------------------------------------------------

def test_redact_env_splits_visible_and_secret() -> None:
    snap = redact_env(
        {"POSTGRES_PASSWORD": "hunter2", "DB_HOST": "db"}, stack_name="my-stack"
    )
    assert snap.visible == {"DB_HOST": "db"}
    assert snap.secret_keys == ["POSTGRES_PASSWORD"]
    assert "POSTGRES_PASSWORD" in snap.secret_hashes_by_key
    # hash is deterministic and salt = stack_name
    assert snap.secret_hashes_by_key["POSTGRES_PASSWORD"] == hash_secret(
        "hunter2", "my-stack"
    )


def test_redact_env_empty_env() -> None:
    snap = redact_env({}, stack_name="x")
    assert snap.visible == {}
    assert snap.secret_keys == []
    assert snap.secret_hashes_by_key == {}


# --- scrub_line ---------------------------------------------------------

def test_scrub_line_replaces_unquoted_secret_value() -> None:
    assert scrub_line("POSTGRES_PASSWORD=hunter2", {"POSTGRES_PASSWORD"}) == "POSTGRES_PASSWORD=***"


def test_scrub_line_replaces_double_quoted_secret_value() -> None:
    assert scrub_line('SECRET="my value"', {"SECRET"}) == "SECRET=***"


def test_scrub_line_replaces_single_quoted_secret_value() -> None:
    assert scrub_line("TOKEN='abc def'", {"TOKEN"}) == "TOKEN=***"


def test_scrub_line_leaves_unrelated_lines_unchanged() -> None:
    assert scrub_line("DATABASE_URL=postgres://x", {"SECRET"}) == "DATABASE_URL=postgres://x"


def test_scrub_line_multiple_keys() -> None:
    line = "POSTGRES_PASSWORD=p SECRET=s"
    assert scrub_line(line, {"POSTGRES_PASSWORD", "SECRET"}) == "POSTGRES_PASSWORD=*** SECRET=***"


def test_scrub_line_escapes_regex_metacharacters_in_key() -> None:
    line = "API.KEY=xyz"
    assert scrub_line(line, {"API.KEY"}) == "API.KEY=***"


def test_redact_text_shell_style_secret() -> None:
    from infra_agent.state.secret_redactor import redact_text

    assert redact_text("password=abc123") == "password=***"


def test_redact_value_deep_nested_dict_key() -> None:
    from infra_agent.state.secret_redactor import redact_value_deep

    out = redact_value_deep({"api_key": "secret-value", "safe": "ok"})
    assert out["api_key"] == "***"
    assert out["safe"] == "ok"


def test_looks_like_credential_uri_detects_embedded_password() -> None:
    from infra_agent.state.secret_redactor import looks_like_credential_uri

    assert looks_like_credential_uri("mongodb://user:pass@mongo:27017/db")
    assert not looks_like_credential_uri("mongodb://mongo:27017/db")


def test_redact_text_masks_credential_uri() -> None:
    from infra_agent.state.secret_redactor import redact_text

    assert (
        redact_text('MONGO_URI="mongodb://admin:secret@db:27017/app"')
        == 'MONGO_URI="mongodb://***@db:27017/app"'
    )


def test_scrub_line_masks_credential_uri_without_known_key() -> None:
    line = "MONGO_URI=mongodb://admin:secret@db:27017/app"
    assert scrub_line(line, set()) == "MONGO_URI=mongodb://***@db:27017/app"
