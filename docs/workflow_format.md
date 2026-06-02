# Workflow format

simpleWorkflow uses a small YAML format focused on scientific shell pipelines.

## Minimal example

```yaml
workflow:
  name: hello_workflow

context:
  message: "hello"

tasks:
  - name: prepare
    run: "echo prepare"

  - name: run
    run: "echo {message}"
    depends_on: [prepare]
```

## Sections

### workflow

Metadata for the workflow. The MVP currently uses `workflow.name` to identify the persisted state.

### context

A mapping of values used to render task commands through Python string formatting.

### tasks

A list of tasks. Each task must define:

- `name`: unique task name.
- `run`: shell command to execute.

Optional fields:

- `depends_on`: one dependency or a list of dependencies.
- `enabled`: set to `false` to skip the task.

## State and restart

Task status is stored in SQLite under `.simpleworkflow/state.sqlite3` by default. Successful tasks are skipped on the next run unless `--force` is used.

## Logs

Each task writes standard output and standard error to `.simpleworkflow/logs/<workflow-name>/`.
