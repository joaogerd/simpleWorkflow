-- Schema copied from simpleWorkflow v0.2.0 tag (2ef6a5b880e05b0537d6ea07df765c10abe8bc71).
CREATE TABLE task_state (
    workflow TEXT NOT NULL,
    task TEXT NOT NULL,
    status TEXT NOT NULL,
    return_code INTEGER,
    signature TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workflow, task)
);
