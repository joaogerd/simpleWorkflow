-- Schema copied from simpleWorkflow 0.3.0 main immediately after PR #16.
CREATE TABLE task_state (
    workflow TEXT NOT NULL,
    task TEXT NOT NULL,
    status TEXT NOT NULL,
    return_code INTEGER,
    signature TEXT,
    reason TEXT,
    attempt_dir TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workflow, task)
);
