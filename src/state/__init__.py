"""State persistence and drift/rollback modules."""

from src.state.drift_detector import detect_drift
from src.state.env_file import (
    EnvValue,
    merge_env,
    parse_env_file,
    read_env_file,
    write_env_file,
)
from src.state.logger import LogEntry, LogLevel, StructuredLogger
from src.state.rollback import (
    KnownGood,
    RollbackPlan,
    capture_known_good,
    plan_rollback,
)
from src.state.secret_redactor import (
    SECRET_KEY_PATTERN,
    hash_secret,
    redact_env,
    scrub_line,
    should_redact,
)
from src.state.session_store import (
    SessionStore,
    format_sessions_list,
    redact_messages,
    session_cwd_mismatch_warning,
)
from src.state.state_store import HistoryEvent, StateStore

__all__ = [
    "SECRET_KEY_PATTERN",
    "capture_known_good",
    "detect_drift",
    "format_sessions_list",
    "hash_secret",
    "HistoryEvent",
    "KnownGood",
    "LogEntry",
    "LogLevel",
    "merge_env",
    "parse_env_file",
    "plan_rollback",
    "read_env_file",
    "redact_env",
    "redact_messages",
    "RollbackPlan",
    "scrub_line",
    "SessionStore",
    "should_redact",
    "StateStore",
    "StructuredLogger",
    "session_cwd_mismatch_warning",
    "write_env_file",
    "EnvValue",
]