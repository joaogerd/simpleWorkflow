# Interactive workflow monitor

simpleWorkflow 0.6 provides an optional terminal user interface (TUI) for
scientists who want to inspect one workflow interactively without turning
simpleWorkflow into a service or centralized orchestrator. The 0.6 release keeps
the persisted-state architecture introduced in 0.4/0.5 and concentrates on
operator workflow: compact task context, attempt history, inspectable resources,
a reusable text/log viewer, direct failure evidence and a broad cycle matrix.

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
and reopening the monitor reconstructs the screen from persisted state; no
in-memory TUI event history is required for recovery.

The default refresh interval is one second and can be changed for an attached
monitor:

```bash
swf monitor workflow.yaml --refresh-seconds 2
```

The monitor performs compact SQLite reads and only inspects attempt metadata or
log files when the Inspector or Logs view needs them. It does not poll the
scheduler independently of the workflow engine.

## Views

The interface has five operational views.

**Monitor** is the default. It shows the workflow tree and task Inspector. The
selected day appears at the upper right with previous/next-day controls. The
cycle strip below the header contains real cycle buttons derived from the
workflow state; it does not assume that every workflow uses 00Z/06Z/12Z/18Z.
Clicking a cycle selects it immediately. Previous/next-cycle buttons continue
through longer campaigns while the compact strip follows the relevant part of
the timeline.

The task tree can be filtered with `/`. Filtering matches the internal task name,
the compact display label and the current task state. The filter is presentation
only and never changes workflow execution or SQLite state.

The Inspector only displays applicable fields. Its compact primary section keeps
status, backend, selected attempt, timing, PBS job ID and return code visible
without reserving large empty areas. Previous/next-attempt controls move through
persisted retry history. A structured resource table exposes files that belong
to the selected attempt: launcher stdout/stderr, PBS stdout/stderr,
`started.json`, `metadata.json`, `scheduler.json`, PBS job scripts and
recorded input/output resources when present. Command, working directory,
dependencies, requested PBS resources and similar lower-frequency fields remain
available under collapsible details.

Selecting an Inspector resource opens the internal read-only viewer. The viewer
supports bounded reads, search, next/previous match, reload, copy, copy-path and
follow/pause for live log streams. The same viewer is embedded in the Logs view,
so there is only one file-reading behavior to learn.

**Ciclos** is the broad operational matrix. Rows are discovered process groups
such as OBS, JEDI and MPAS; columns are the actual native or safe presentation
cycles in chronological order. It does not assume 00Z/06Z/12Z/18Z. Each
non-empty process/cycle cell aggregates the statuses of the tasks in that
intersection and selecting the cell returns to Monitor at the corresponding
cycle. Empty intersections remain inert.

**Campanha** is a navigable campaign overview. It groups the available cycles by
day, summarizes the number of cycles and task states for that day, and lets a
selected day jump directly back to Monitor. The compact run/instance metadata is
kept as context rather than dominating the view. Clicking the current date in
the header opens the campaign view at the selected day.

**Problemas** contains only conditions that require attention, such as failure,
invalid input/output, blocked dependencies, interrupted or uncertain work. The
tab shows a problem count when attention is required. With no such state it
displays `No problems detected.` Selecting a problem preserves the task/cycle
context and follows a deterministic shortest path to evidence: PBS stderr,
stderr, PBS stdout, stdout. If no stream exists, Monitor/Inspector is shown with
the persisted reason instead of fabricating a process log.

**Logs** is deliberately separate from Monitor but uses the same
`TextFileViewer` as Inspector resources. It can display launcher stdout/stderr
and, for PBS attempts, PBS stdout/stderr when those files are present. Missing
files are normal and never make the monitor fail. `FOLLOW ●` updates the visible
log as the file grows; `f` or the follow button pauses updates while the
operator inspects existing output, and pressing it again resumes from persisted
content. Search, copy, path-copy and reload work the same way as in the modal
resource viewer.

Visible log text is also scanned conservatively for related files. Only existing
regular files referenced by absolute paths or explicit `./` / `../` paths are
offered. Structured attempt resources always take precedence, duplicates are
suppressed, and the feature never becomes an arbitrary recursive file browser.

## Native and unrolled scientific cycles

Native simpleWorkflow cycling uses persisted `cycle_state` and task state keyed
by `(cycle, task)`. Those persisted cycles always have priority in the monitor.

Some scientific workflows deliberately place several analysis times in one
unrolled task graph so that cross-cycle dependencies are ordinary dependencies
inside one engine run. The MONAN-JEDI corrected replay is an example of this
shape. For presentation only, the monitor can reconstruct a timeline from
explicit `--cycle` arguments already present in task commands.

A task without an explicit cycle inherits a presentation cycle only when every
one of its dependencies has already been assigned and all of those dependencies
belong to the same cycle. This allows a validation gate to follow its stage while
remaining conservative: cross-cycle joins, tasks depending on global work,
shared setup tasks, and any ambiguous task stay outside the cycle groups.

Those tasks appear once under a small `Workflow` section in Monitor. Their
Inspector reports their scope as `workflow`, making it clear that they were not
forced into 00Z, 06Z or another cycle simply to complete the timeline.

This grouping changes no execution state:

```text
state.sqlite3             workflow.yaml
     │                         │
     │ task status             │ explicit --cycle/dependencies
     └──────────┬──────────────┘
                ▼
         MonitorSnapshot
                │
                ▼
               TUI
```

No artificial `cycle_state` is written, no task name is used to guess a cycle,
and no dependency is changed by the monitor.

## Navigation

The deliberately small shortcut set is:

```text
↑ / ↓        select task when the tree has focus
← / →        previous / next cycle
/            filter tasks
Enter        inspect selected task on narrow terminals
Esc          clear filter / return to workflow
Tab          next view
Shift+Tab    previous view
1..5         Monitor / Ciclos / Campanha / Problemas / Logs
l            logs for selected task
o / e        preferred output / error log
f            follow / pause log updates
r            refresh now
?            help overlay
q            close monitor
```

The date controls, cycle buttons, campaign rows, cycle-matrix cells, Inspector
attempt/resource controls, problem rows, log-stream selectors and related-file
rows are also clickable. The help overlay only lists commands that exist; there
is no permanent Help tab.

Wide terminals show workflow and Inspector side by side, with a compact daily
process/cycle matrix below the Inspector. Narrow terminals keep the workflow
readable and provide the Inspector as an alternate pane instead of compressing
both columns beyond usefulness. The permanent shortcut line is shortened on
narrow terminals; `?` remains the complete help surface.

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

Task commands, working directories, scheduler metadata and resource locations
are read from immutable attempt directories under `.simpleworkflow/runs/` when
available. Multiple persisted attempts remain selectable. These files enrich
presentation; they do not override SQLite task state. Incomplete or missing
provenance simply results in fewer Inspector fields or unavailable resources.

PBS metadata is inspection-only. The monitor reads the recorded job ID, job
script, scheduler JSON and worker streams; it does not call `qstat`, `qdel` or
`qsub`. Scheduler interaction remains the responsibility of the execution
engine, not the TUI.

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
