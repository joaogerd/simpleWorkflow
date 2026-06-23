# simpleWorkflow

simpleWorkflow is a lightweight YAML workflow runner for scientific pipelines. It provides dependency ordering, persistent task state and per-task logs without requiring a full workflow platform.

It is not intended to replace Cylc or ecFlow in large operational systems. It covers the middle ground between ad-hoc scripts and larger workflow systems.

## MVP features

- YAML workflow definition;
- dependency-aware task ordering;
- local execution from explicit program argument vectors;
- CLI commands for planning, running, status and reset;
- persistent SQLite state for restart support;
- per-task stdout and stderr logs;
- context variables rendered into task arguments, working directories and environment values.

## Installation

```bash
git clone https://github.com/joaogerd/simpleWorkflow.git
cd simpleWorkflow
python -m pip install -e .
```

## Quick start

```bash
simpleworkflow plan examples/hello.yaml
simpleworkflow run examples/hello.yaml
simpleworkflow status examples/hello.yaml
simpleworkflow reset examples/hello.yaml
```

Use `--force` to rerun successful tasks and `--dry-run` to preview the resolved argument vectors.

## Workflow format

A task uses `argv`, never a shell command string. The following task runs the `printf` executable with three explicit arguments:

```yaml
tasks:
  - name: prepare
    argv: [printf, '%s\n', Preparing workflow]
```

See [`docs/workflow_format.md`](docs/workflow_format.md) for the full contract.

## State and logs

Runtime files are written under `.simpleworkflow/` by default:

```text
.simpleworkflow/
  state.sqlite3
  logs/<workflow-name>/<task>.out
  logs/<workflow-name>/<task>.err
```

## Development

```bash
python -m pytest
```

## License

This project is licensed under the MIT License.
