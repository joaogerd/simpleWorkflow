# simpleWorkflow

`simpleWorkflow` is a lightweight YAML workflow runner for scientific pipelines.
It provides dependency ordering, restart-safe state, immutable task attempts and
simple local or PBS execution without requiring a workflow server, a daemon or a
site-specific platform.

It deliberately does **not** compete with Cylc, ecFlow, Airflow or similar
orchestrators. Use it when a researcher needs a small, inspectable and
reproducible workflow that can be installed and understood quickly.

## What it provides

- YAML task definitions with explicit `argv` arguments, never shell command strings;
- dependency-aware, sequential execution;
- `plan`, `validate`, `run`, `status`, `explain`, `reset` and `migrate` commands;
- exclusive execution, persistent state and conservative restart/reuse;
- required input/output artifact validation;
- per-attempt logs and provenance records;
- ISO-8601 cycle expansion for scientific cases;
- controlled local execution and a small PBS foreground-wait backend;
- friendly, color-aware progress output with no runtime dependency.

## Deliberate limits

`simpleWorkflow` has no scheduler daemon, web UI, distributed controller,
implicit shell language, remote worker protocol or generalized event system.
Those features belong in larger orchestration platforms.

A `.simpleworkflow` directory belongs to one logical workflow instance. It is
not a registry or manager for many workflows.

## Installation

```bash
git clone https://github.com/joaogerd/simpleWorkflow.git
cd simpleWorkflow
python -m pip install -e .
```

For development tools and tests:

```bash
python -m pip install -e ".[dev]"
```

## Quick start

```bash
swf plan examples/hello.yaml
swf validate examples/hello.yaml
swf run examples/hello.yaml
swf status examples/hello.yaml
swf explain examples/hello.yaml
swf reset examples/hello.yaml
```

Use `--force` to rerun successful tasks and `--dry-run` to inspect rendered
argument vectors without launching processes.

`plan` and `validate` do not create persistent state. Commands that need state
use `.simpleworkflow` beside the workflow YAML by default, regardless of the
shell's current directory.

## Terminal output

The CLI prints compact lifecycle events such as `PLAN`, `RUN`, `OK`, `FAIL`,
`SKIP` and `RERUN`. Interactive terminals receive color and symbols by default;
redirected output stays plain so logs and scripts remain stable.

```bash
# Default: color only when stdout is interactive.
swf run workflow.yaml

# Demonstrations or terminals that do not advertise color.
swf run workflow.yaml --color always

# CI logs, shell parsing or plain text output.
swf status workflow.yaml --color never
```

`--color` accepts `auto`, `always` and `never`. Setting `NO_COLOR` also disables
automatic color. The terminal renderer uses only Python's standard library.

## Workflow format

A task uses `argv`, never a shell command string. Each list item is exactly one
program argument:

```yaml
format_version: 1

workflow:
  name: hello

context:
  python: python

tasks:
  - name: prepare
    argv: ["{python}", "-c", "print('Preparing workflow')"]
```

Task arguments, working directories, environment values and artifact paths can
use context placeholders such as `{python}`, `{case_name}` and
`{cycle_yyyymmddhh}`. See [the workflow format](docs/workflow_format.md).

## One workflow, one state directory

The normal layout is:

```text
WORKFLOW ROOT/
├── workflow.yaml
└── .simpleworkflow/
    ├── state.sqlite3
    ├── lock
    ├── logs/
    └── runs/
```

For example:

```bash
swf run /work/experiment/workflow.yaml
```

uses:

```text
/work/experiment/.simpleworkflow/state.sqlite3
```

The database stores one workflow instance with its tasks, cycles, current state,
runs, attempts and history. An internal UUID identifies that instance, but users
do not put the UUID in YAML and do not use it to run the workflow.

Move the complete workflow root, including `.simpleworkflow`, to preserve the
same execution naturally. The absolute YAML path is diagnostic metadata, not
workflow identity, and task signatures use portable paths for files inside the
workflow root.

See [persistent state model](docs/state-model.md) for the full contract.

## Cycles

Scientific cycles are part of the same logical workflow, not separate
workflows. A cycling campaign therefore keeps one `state.sqlite3` and records
state separately per `(cycle, task)`.

```text
workflow instance
├── 20180415T000000Z
├── 20180415T060000Z
└── 20180415T120000Z
```

The human `workflow.name` remains unchanged across cycles.

## Upgrading state from 0.2.x or 0.3.x

0.4.0 introduces the first explicitly versioned state schema. Legacy databases
are never rewritten automatically.

Inspect first:

```bash
swf migrate workflow.yaml --check
```

Then migrate an unambiguous workflow:

```bash
swf migrate workflow.yaml
```

Migration creates a backup automatically before replacing `state.sqlite3`.
Legacy shared databases containing multiple logical workflows are detected and
refused unless one instance is explicitly selected and migrated from its own
copy of the legacy state directory.

Read [upgrading to 0.4.0](docs/upgrade-0.4.md) before upgrading an existing
scientific experiment.

## PBS execution

PBS tasks remain intentionally simple. The runner creates one `job.pbs`, submits
it with `qsub`, records the job identifier immediately and consults `qstat` in
the foreground until a final result is available. No service or daemon is used.

```yaml
- name: analysis
  executor: pbs
  argv: [bash, run_analysis.sh, "{cycle_yyyymmddhh}"]
  cwd: "{project_root}"
  pbs:
    queue: pesqmini
    project: monan_das
    walltime: "00:30:00"
    select: 1
    ncpus: 128
    mpiprocs: 128
    omp_threads: 1
    block: true
```

The full contract, runtime files and JACI-oriented notes are in
[PBS execution](docs/pbs.md).

## State, logs and provenance

Runtime files are written below the workflow's `.simpleworkflow/` by default:

```text
.simpleworkflow/
  state.sqlite3
  lock
  runs/<run-id>/
    run.json
    tasks/<task>-<digest>/attempt-001/
      stdout.log          # launcher or local process output
      stderr.log
      metadata.json       # command, inputs, outputs, signature and backend
      job.pbs             # PBS tasks only
      pbs.stdout.log      # PBS job output
      pbs.stderr.log
```

A successful task is reused only when its signature still matches and required
outputs pass their declared checks. Signatures include the effective task,
execution backend, declared environment, safe hashes of relevant inherited
environment values, executable identity and declared input fingerprints. Paths
inside the workflow root are location-independent, so moving the complete case
does not itself force a rerun. Each run also preserves the effective YAML.

See [operations and recovery](docs/operations.md) before using a workflow for a
scientific baseline or PBS campaign.

## Development

```bash
python -m ruff check simpleworkflow
python -m mypy
python -m pytest --cov=simpleworkflow
```

## Legacy implementation

The `legacy/` directory contains historical code from before the package
redesign. It is not distributed, not run by CI and must not be used
by new workflows. See [legacy notes](docs/legacy.md).

## License

This project is licensed under the MIT License.
