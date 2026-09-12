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
- `plan`, `run`, `status`, `reset` and interactive `tui` commands;
- persistent SQLite task state and safe restart/reuse;
- required input/output artifact validation;
- per-attempt logs and provenance records;
- ISO-8601 cycle expansion for scientific cases;
- local execution and a small blocking PBS backend;
- concise Rich terminal progress plus an optional full-screen Textual monitor.

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
swf tui examples/hello.yaml
swf reset examples/hello.yaml
```

Use `--force` to rerun successful tasks and `--dry-run` to inspect rendered
argument vectors without launching processes.

## Terminal output

The normal CLI view is intended for scientific and operational users. It shows
the workflow, execution mode, progress, human-facing stages and the final result
without printing every rendered command.

Task names that follow the common `componentHH_action` convention are grouped
automatically. For example, `jedi06_prepare`, `jedi06_submit` and
`jedi06_validate` are presented under `JEDI 06Z` with the actions `Prepare`,
`Submit` and `Validate`. The internal task names remain unchanged and continue
to be used for state, logs and provenance.

Typical output emphasizes states such as `RUNNING`, `SUCCESS`, `REUSED`,
`RERUN` and `FAILED`, followed by an end-of-run summary with elapsed time and
the next useful action.

```bash
# Concise scientific/operational view.
swf run workflow.yaml

# Include internal task names, executors and rendered commands.
swf run workflow.yaml --verbose

# Stable linear output in an interactive terminal.
swf run workflow.yaml --plain

# Demonstrations or terminals that do not advertise color.
swf run workflow.yaml --color always

# CI logs, redirected output or plain text terminals.
swf status workflow.yaml --color never
```

`--color` accepts `auto`, `always` and `never`. Setting `NO_COLOR` also disables
automatic color. Detailed stdout/stderr and provenance records remain stored
separately below the workflow work directory.

## Interactive TUI

`swf tui` opens a full-screen Textual monitor inspired by the operational ideas
used by ecFlow and Cylc, while keeping workflow execution and persisted state
independent of the interface.

```bash
swf tui workflow.yaml --workdir .simpleworkflow
```

For workflows with explicit `--cycle` timestamps, the operational view is
organized around one selected date. At most four synoptic cycles are visible at
once: `00Z`, `06Z`, `12Z` and `18Z`. Previous/next-day buttons and the left/right
keys move the selected date, while `1`, `2`, `3` and `4` select those cycles.
Shift+left/right moves by month.

The TUI separates information into clickable tabs:

- **Monitor** — the selected cycle workflow, task inspector and current log;
- **Matriz** — component-by-cycle status for the selected date;
- **Campanha** — a monthly map of complete, running, failed, partial and waiting days;
- **Problemas** — failed tasks only;
- **Logs** — expanded output for the selected task;
- **Ajuda** — keyboard navigation and status legend.

The selected task inspector is refreshed from the real `state.sqlite3` database
and newest immutable runtime attempt. It shows executor, return code, configured
PBS resources and Job ID when those details are available in attempt metadata.
The Monitor and Logs views tail the persisted stdout/stderr files rather than
simulating scientific output.

Generic workflows without explicit cycle timestamps continue to work in a
non-dated monitor mode.

The first monitor is intentionally read-only. Monitoring should not change
workflow state. Destructive operational actions such as scheduler cancellation
or selective reruns can be added later with explicit confirmation and dedicated
tests.

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
