# Workflow format

simpleWorkflow defines dependency-aware tasks that execute explicit program argument vectors. It does not invoke a shell.

## Task fields

Each task must define a unique `name` and a non-empty `argv` list. Each item of `argv` is one exact process argument and supports context placeholders such as `{python}` or `{case_name}`.

Optional fields are `depends_on`, `enabled`, `cwd`, `env`, and `executor`.

`cwd` is the task working directory. Relative paths are interpreted from the directory containing the workflow YAML file. `env` is a mapping of task-specific environment values. The only supported executor at this stage is `local`.

The former `run` field is deliberately unsupported. A single command string would require shell parsing and permit implicit redirection, pipelines and environment expansion.

## Context

`context` is a mapping used to render string elements of `argv`, `cwd`, and `env` using Python format placeholders.

## State and logs

Task status is stored in SQLite under `.simpleworkflow/state.sqlite3` by default. Successful tasks are skipped on subsequent runs unless `--force` is used. Standard output and standard error are stored under `.simpleworkflow/logs/<workflow-name>/`.
