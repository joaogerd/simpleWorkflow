from simpleworkflow.lifecycle import (
    ATTENTION_STATES,
    BLOCKED,
    COMPLETE_STATES,
    FAILED,
    INTERRUPTED,
    INVALID_INPUT,
    INVALID_OUTPUT,
    PENDING,
    PERSISTED_TASK_STATES,
    REUSABLE_STATES,
    RUNNING,
    SKIPPED,
    STALE,
    SUCCESS,
    TASK_STATES,
    TERMINAL_STATES,
    UNAVAILABLE_DEPENDENCY_STATES,
    UNKNOWN,
)


def test_task_state_vocabulary_is_complete() -> None:
    assert TASK_STATES == {
        PENDING,
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
    assert PENDING not in PERSISTED_TASK_STATES
    assert PERSISTED_TASK_STATES == TASK_STATES - {PENDING}


def test_lifecycle_semantic_groups_are_consistent() -> None:
    assert COMPLETE_STATES == {SUCCESS, SKIPPED}
    assert REUSABLE_STATES == {SUCCESS}
    assert ATTENTION_STATES == {
        FAILED,
        INVALID_INPUT,
        INVALID_OUTPUT,
        BLOCKED,
        INTERRUPTED,
        UNKNOWN,
    }
    assert UNAVAILABLE_DEPENDENCY_STATES == ATTENTION_STATES | {SKIPPED}
    assert TERMINAL_STATES == {
        SUCCESS,
        FAILED,
        INVALID_INPUT,
        INVALID_OUTPUT,
        SKIPPED,
        BLOCKED,
        INTERRUPTED,
        UNKNOWN,
    }
    assert RUNNING not in TERMINAL_STATES
    assert STALE not in TERMINAL_STATES
