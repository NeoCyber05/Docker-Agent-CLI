"""State persistence and drift/rollback modules."""

from docker_agent.state.drift_detector import detect_drift
from docker_agent.state.env_file import (
    EnvValue,
    merge_env,
    parse_env_file,
    read_env_file,
    write_env_file,
)
from docker_agent.state.logger import LogEntry, LogLevel, StructuredLogger
from docker_agent.state.rollback import (
    KnownGood,
    RollbackPlan,
    capture_known_good,
    plan_rollback,
)
from docker_agent.state.secret_redactor import (
    SECRET_KEY_PATTERN,
    hash_secret,
    redact_env,
    scrub_line,
    should_redact,
)
from docker_agent.state.session_store import (
    SessionStore,
    format_sessions_list,
    redact_messages,
    session_cwd_mismatch_warning,
)
from docker_agent.state.state_store import HistoryEvent, StateStore

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