"""Shared lifecycle state names and semantic groupings.

Presentation modules remain responsible for labels, symbols and colors. This
module only defines the small vocabulary that execution, persistence and
monitoring use to make decisions.
"""

PENDING = "pending"
RUNNING = "running"
SUCCESS = "success"
FAILED = "failed"
INVALID_INPUT = "invalid-input"
INVALID_OUTPUT = "invalid-output"
SKIPPED = "skipped"
STALE = "stale"
BLOCKED = "blocked"
INTERRUPTED = "interrupted"
UNKNOWN = "unknown"

PERSISTED_TASK_STATES = frozenset(
    {
        RUNNING,
        SUCCESS,
        FAILED,
        INVALID_INPUT,
        INVALID_OUTPUT,
        SKIPPED,
        STALE,
        BLOCKED,
        INTERRUPTED,
        UNKNOWN,
    }
)

COMPLETE_STATES = frozenset({SUCCESS, SKIPPED})
ATTENTION_STATES = frozenset(
    {
        FAILED,
        INVALID_INPUT,
        INVALID_OUTPUT,
        BLOCKED,
        INTERRUPTED,
        UNKNOWN,
    }
)
UNAVAILABLE_DEPENDENCY_STATES = ATTENTION_STATES | frozenset({SKIPPED})
REUSABLE_STATES = frozenset({SUCCESS})
