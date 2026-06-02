# simpleWorkflow

simpleWorkflow is a lightweight YAML workflow runner for scientific pipelines.

The goal is to provide a simple, fast and practical layer to organize CPTEC/INPE scientific workflows before they become large shell scripts that are difficult to maintain.

This project is not intended to replace Cylc or ecFlow in full operational environments. It is intended to cover the middle ground between ad-hoc shell scripts and large workflow systems.

## MVP features

- YAML workflow definition.
- Dependency-aware task ordering.
- Local shell execution.
- CLI commands for planning, running, checking status and resetting state.
- Persistent SQLite state for simple restart support.
- Per-task stdout/stderr logs.
- Context variables rendered into task commands.
- Examples inspired by MONAN-JEDI and SMNA workflows.

## Installation

```bash
git clone https://github.com/joaogerd/simpleWorkflow.git
cd simpleWorkflow
python -m pip install -e .
```

## Quick start

Show the execution plan:

```bash
simpleworkflow plan examples/hello.yaml
```

Run the example workflow:

```bash
simpleworkflow run examples/hello.yaml
```

Check task status:

```bash
simpleworkflow status examples/hello.yaml
```

Reset workflow state:

```bash
simpleworkflow reset examples/hello.yaml
```

Force a full rerun:

```bash
simpleworkflow run examples/hello.yaml --force
```

Preview commands without executing them:

```bash
simpleworkflow run examples/hello.yaml --dry-run
```

## Workflow format

A minimal workflow looks like this:

```yaml
workflow:
  name: hello_workflow

context:
  message: "simpleWorkflow MVP is running"

tasks:
  - name: prepare
    run: "echo Preparing workflow"

  - name: run
    run: "echo {message}"
    depends_on: [prepare]
```

See [`docs/workflow_format.md`](docs/workflow_format.md) for details.

## State and logs

By default, runtime files are written under `.simpleworkflow/`:

```text
.simpleworkflow/
  state.sqlite3
  logs/<workflow-name>/<task>.out
  logs/<workflow-name>/<task>.err
```

Successful tasks are skipped in later runs unless `--force` is used.

## Examples

- `examples/hello.yaml`: minimal local workflow.
- `examples/monan_jedi_3dvar.yaml`: MONAN-JEDI 3DVar-FGAT tutorial sequence.
- `examples/smna_gsi_bam.yaml`: SMNA-style OBSMAKE -> GSI -> BAM -> diagnostics sequence.

## Roadmap

See [`docs/roadmap.md`](docs/roadmap.md).

## Development

Run tests with:

```bash
python -m pytest
```

## License

This project is licensed under the MIT License.
