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
- `plan`, `run`, `status` and `reset` commands;
- persistent SQLite task state and safe restart/reuse;
- required input/output artifact validation;
- per-attempt logs and provenance records;
- ISO-8601 cycle expansion for scientific cases;
- local execution and a small blocking PBS backend;
- a Rich-based scientific terminal dashboard with a stable plain-text fallback.

## Deliberate limits

`simpleWorkflow` has no scheduler daemon, web UI, distributed controller,
implicit shell language, remote worker protocol or generalized event system.
Those features belong in larger orchestration platforms.

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
swf run examples/hello.yaml
swf status examples/hello.yaml
swf reset examples/hello.yaml
```

Use `--force` to rerun successful tasks and `--dry-run` to inspect rendered
argument vectors without launching processes.

## Terminal dashboard

Interactive terminals use an ecFlow/Cylc-inspired Rich dashboard. The left side
shows the execution hierarchy and individual task state; the right side shows a
cycle matrix that makes it easy to see which scientific components have
completed, are running, failed or are still waiting.

Task names that follow the common `componentHH_action` convention are grouped
automatically. For example, `jedi06_prepare`, `jedi06_submit` and
`jedi06_validate` appear under `JEDI 06Z`, while the cycle matrix summarizes the
state of JEDI, MPAS and observation-processing stages across the available
cycles.

During `swf run`, the dashboard is refreshed in place. Completed tasks show their
elapsed time. The current activity is highlighted separately, and a final panel
summarizes the result, elapsed time and next useful action.

The workflow engine does not invent progress percentages. A stage is shown as
`RUNNING` while its task is active unless the underlying scientific application
provides a real progress signal in a future integration.

```bash
# Live scientific dashboard in an interactive terminal.
swf run workflow.yaml

# Static dashboard showing the current state.
swf status workflow.yaml

# Include internal task names, executor names and rendered commands.
swf run workflow.yaml --verbose

# Stable linear output for logs, CI or shell processing.
swf run workflow.yaml --plain

# Disable ANSI color while keeping the same information.
swf status workflow.yaml --color never
```

Redirected output automatically falls back to the linear representation. `--plain`
can be used to force that representation even in an interactive terminal.
`--color` accepts `auto`, `always` and `never`; setting `NO_COLOR` also disables
automatic color.

The dashboard is presentation only. Task state, stdout/stderr, commands,
signatures and provenance remain stored separately below the workflow work
directory and are unaffected by the terminal renderer.

## Workflow format

A task uses `argv`, never a shell command string. Each list item is exactly one
program argument:

```yaml
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

## PBS execution

PBS tasks remain intentionally simple. The runner creates one `job.pbs` file,
submits it with `qsub -W block=true`, and waits for its final result before
advancing the workflow. This preserves the same success/failure semantics used
by local tasks.

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

Runtime files are written below `.simpleworkflow/` by default:

```text
.simpleworkflow/
  state.sqlite3
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

A successful task is reused only when its signature still matches, required
outputs still exist and no dependency executed again in the current invocation.
If an upstream task is executed again, that rerun propagates safely through its
dependent tasks. Signatures include the rendered invocation, declared
environment, workflow file and declared input fingerprints.

## Development

```bash
python -m ruff check simpleworkflow
python -m mypy
python -m pytest --cov=simpleworkflow
```

## Legacy implementation

The `app/` and `unittests/` directories are historical code from before the
package redesign. They are not distributed, not run by CI and must not be used
by new workflows. See [legacy notes](docs/legacy.md).

## License

This project is licensed under the MIT License.
