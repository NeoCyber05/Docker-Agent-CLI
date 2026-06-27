"""Parity tests for env_file — mirrors src/state/envFile.ts."""

import os
import sys
from pathlib import Path

import pytest

from src.state.env_file import (
    merge_env,
    parse_env_file,
    read_env_file,
    write_env_file,
)

# --- parse_env_file -----------------------------------------------------

def test_parse_empty_and_comments() -> None:
    assert parse_env_file("\n# comment\n\n") == {}


def test_parse_basic_key_value() -> None:
    assert parse_env_file("KEY=value\n") == {"KEY": "value"}


def test_parse_inline_comment_unquoted() -> None:
    assert parse_env_file("KEY=value # not used\n") == {"KEY": "value"}


def test_parse_double_quoted_value() -> None:
    assert parse_env_file('KEY="hello world"\n') == {"KEY": "hello world"}


def test_parse_single_quoted_value() -> None:
    assert parse_env_file("KEY='hello world'\n") == {"KEY": "hello world"}


def test_parse_quoted_value_with_trailing_comment_allowed() -> None:
    assert parse_env_file('KEY="hello" # a comment\n') == {"KEY": "hello"}


def test_parse_quoted_value_with_garbage_after_rejected() -> None:
    # line dropped entirely
    assert parse_env_file('KEY="hello" trailing\n') == {}


def test_parse_unclosed_quote_rejected() -> None:
    assert parse_env_file('KEY="hello\n') == {}


def test_parse_equals_in_value() -> None:
    assert parse_env_file("KEY=a=b\n") == {"KEY": "a=b"}


def test_parse_empty_key_dropped() -> None:
    assert parse_env_file("=value\n") == {}


def test_parse_crlf_line_endings() -> None:
    assert parse_env_file("KEY=value\r\nNEXT=2\r\n") == {"KEY": "value", "NEXT": "2"}


# --- read_env_file ------------------------------------------------------

def test_read_env_file_missing_returns_empty(tmp_path: Path) -> None:
    assert read_env_file(str(tmp_path / "missing.env")) == {}


def test_read_env_file_reads_existing_file(tmp_path: Path) -> None:
    p = tmp_path / "x.env"
    p.write_text("KEY=value\n")
    assert read_env_file(str(p)) == {"KEY": "value"}


# --- write_env_file -----------------------------------------------------

def test_write_env_file_basic(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "x.env"
    write_env_file(str(p), {"KEY": "value"})
    assert p.exists()
    assert p.read_text() == "KEY=value\n"
    # mode should be 0o600 (Unix only; Windows does not honor chmod the same way)
    if sys.platform != "win32":
        assert (os.stat(p).st_mode & 0o777) == 0o600


def test_write_env_file_quotes_values_with_whitespace(tmp_path: Path) -> None:
    p = tmp_path / "test-env-write-py-02.env"
    write_env_file(str(p), {"KEY": "hello world"})
    assert p.read_text() == 'KEY="hello world"\n'


def test_write_env_file_rejects_unsupported_characters(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_env_file(str(tmp_path / "x.env"), {"KEY": 'has"quote'})
    with pytest.raises(ValueError):
        write_env_file(str(tmp_path / "x.env"), {"KEY": "has\nnewline"})


# --- merge_env ----------------------------------------------------------

def test_merge_env_prefers_inline() -> None:
    assert merge_env({"A": "file"}, {"A": "inline"}) == {"A": "inline"}


def test_merge_env_coerces_numbers_and_booleans() -> None:
    assert merge_env({}, {"N": 42, "B": True}) == {"N": "42", "B": "True"}


def test_merge_env_keeps_untouched_file_keys() -> None:
    assert merge_env({"A": "file", "B": "file"}, {"B": "inline"}) == {
        "A": "file",
        "B": "inline",
    }