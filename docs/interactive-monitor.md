# Interactive workflow monitor

simpleWorkflow 0.5 adds an optional terminal user interface (TUI) for scientists
who want to watch one workflow interactively without turning simpleWorkflow into
a service or centralized orchestrator.

The SQLite state introduced in 0.4 remains the source of truth. The TUI is a
read-only presentation layer over the same workflow instance, cycles, tasks,
runs and attempts used by the command-line engine. There is no daemon, server,
socket, REST API or separate scheduler process.

## Installation

The core package stays lightweight:

```bash
python -m pip install simpleworkflow
```

This installs the YAML runner and plain terminal reporter without Textual or
Rich. To enable the full-screen monitor, install the optional TUI extra:

```bash
python -m pip install "simpleworkflow[tui]"
```

Development installations use the same separation:

```bash
python -m pip install -e .
python -m pip install -e ".[tui]"
python -m pip install -e ".[dev]"
```

The development extra includes the TUI libraries so the headless presentation
tests can run in CI.

## `run` presentation modes

`swf run` accepts three presentation modes:

```bash
swf run workflow.yaml --ui auto
swf run workflow.yaml --ui tui
swf run workflow.yaml --ui plain
```

`auto` is the default. It chooses the TUI only when stdin and stdout are real
terminal devices, `TERM` is not `dumb`, and the optional TUI dependencies are
installed. Redirected output, pipes, CI, batch/PBS stdout, `TERM=dumb`, and core
installations without `[tui]` automatically use the plain `TerminalReporter`.

The plain frontend remains the stable interface for logs and automation:

```text
▶ RUN       prepare [local]
✔ OK        prepare [local]
```

`--ui tui` explicitly requires the optional TUI dependencies and reports the
installation command when they are absent. `--ui plain` always bypasses the TUI.

`--dry-run` is intentionally plain because a dry run does not create persistent
execution state to monitor.

Color remains separately controlled by `--color auto|always|never` and
`NO_COLOR`. Workflow states always have symbols as well as color, so monochrome
terminals and screenshots remain understandable.

## Attaching to an existing workflow

A monitor can be opened independently of the process that started execution:

```bash
swf monitor workflow.yaml
```

By default it reads:

```text
<workflow-directory>/.simpleworkflow/state.sqlite3
```

Use the same `--workdir` that was used for execution when state lives elsewhere:

```bash
swf monitor workflow.yaml --workdir /path/to/state
```

The monitor opens existing SQLite state read-only. If no state exists yet, it
shows the configured workflow as pending and does not create a database. Closing
and reopening the monitor reconstructs the screen from persisted state and
attempt provenance; no in-memory TUI state is needed for restart recovery.

The default refresh interval is one second and can be changed for an attached
monitor:

```bash
swf monitor workflow.yaml --refresh-seconds 2
```

The monitor performs compact SQLite reads and only inspects attempt metadata or
log files when the Inspector or Logs view needs them. It does not poll the
scheduler independently of the workflow engine.

## Views

The approved interface has five operational views.

**Monitor** is the default. It shows a compact workflow/cycle tree and an
Inspector for the selected task. The Inspector only displays applicable fields,
including backend, attempt, timing, command, working directory, PBS job ID,
return code, dependencies, declared outputs and requested PBS resources when
those values are available.

**Ciclos** aggregates completed, running, failed and pending tasks for each
persisted cycle. Selecting a cycle returns to Monitor at that cycle.

**Campanha** summarizes the workflow instance, current/latest run, elapsed time,
cycle count and task totals. It does not invent an ETA.

**Problemas** contains only conditions that require attention, such as failure,
invalid input/output, blocked dependencies, interrupted or uncertain work. With
no such state it displays `No problems detected.` Selecting a problem opens the
most useful available error log when possible.

**Logs** is deliberately separate from Monitor. It can display launcher stdout
and stderr and, for PBS attempts, PBS stdout/stderr when those files are present.
Missing files are normal and never make the monitor fail.

## Navigation

The intentionally small shortcut set is:

```text
↑ / ↓        select task
← / →        previous / next cycle
Enter        inspect on narrow terminals
Esc          return to workflow on narrow terminals
Tab          next view
Shift+Tab    previous view
1..5         Monitor / Ciclos / Campanha / Problemas / Logs
l            logs for selected task
o / e        preferred output / error log
r            refresh now
?            help overlay
q            close monitor
```

The help overlay only lists commands that exist; there is no permanent Help tab.

Wide terminals show workflow and Inspector side by side. Narrow terminals keep
the workflow usable and let `Enter` switch to the Inspector instead of trying to
compress both panes into unreadable columns.

## What `q` means

`q` closes the monitor. It is not a workflow cancellation command.

For a separately attached `swf monitor`, execution is unaffected. For
`swf run --ui tui`, the engine runs independently of the Textual presentation
inside the same simpleWorkflow process. If the TUI is closed before execution
finishes, the command continues waiting for the workflow result; it does not
send a signal to the local process or a delete request to PBS.

Cancellation and scheduler control are intentionally outside the TUI navigation
contract.

## Persisted truth and attempt provenance

Operational state comes from `state.sqlite3`:

```text
workflow_instance
cycle_state
task_state
state_event
run_history
attempt_history
```

Task commands, working directories, scheduler metadata and log locations are
read from the immutable attempt directories under `.simpleworkflow/runs/` when
available. These files enrich presentation; they do not override the SQLite task
state. Incomplete or missing provenance simply results in fewer Inspector fields.

This separation is what allows this sequence without a controller service:

```text
workflow executing
       │
       ├── writes persistent state
       │
       ├── plain reporter can be used
       │
       └── monitor can open / close / reopen
                    │
                    ▼
             same state.sqlite3
```
