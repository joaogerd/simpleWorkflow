# Workflow format

Version 1 of `simpleWorkflow` defines dependency-aware tasks that execute explicit program
argument vectors. It does not parse a shell command language.

## Minimal workflow

```yaml
format_version: 1

workflow:
  name: example

context:
  python: python

tasks:
  - name: prepare
    argv: ["{python}", "-c", "print('preparing')"]

  - name: run
    argv: ["{python}", "-c", "print('running')"]
    depends_on: [prepare]
```

Every task requires a unique `name` and a non-empty `argv` list. Each `argv`
item is one exact process argument and supports context placeholders such as
`{python}` and `{case_name}`.

## Task fields

Only the following fields are accepted. Unknown fields fail validation early so
misspellings do not silently alter an experiment.

| Field | Meaning |
| --- | --- |
| `name` | Unique task identifier. |
| `argv` | Required list of explicit program arguments. |
| `depends_on` | One task name or a list of upstream task names. |
| `enabled` | Optional boolean; disabled tasks are recorded as skipped during real execution. |
| `cycle_scope` | Optional closed selector: `all`, `first`, `not_first`, `last`, or `not_last`. Default: `all`. |
| `cwd` | Optional working directory, relative to the workflow YAML when not absolute. |
| `env` | Optional mapping of task-specific string environment variables. |
| `executor` | `local` (default) or `pbs`. |
| `pbs` | Required PBS settings when `executor: pbs`; see [PBS execution](pbs.md). |
| `inputs` | Declared input artifact contract. |
| `outputs` | Declared output artifact contract. |
| `input_fingerprint` | `metadata` (default) or `sha256`. |
| `timeout` | Optional local time limit in seconds; stops the whole process group. |

The historical `run` field is deliberately unsupported. A single command string
would require shell parsing and could introduce implicit redirection, pipelines
or expansion rules. A workflow may still run a controlled wrapper script by
using it explicitly in `argv`.

## Artifact contract

Tasks may declare scientific input and output artifacts. Required inputs are
rendered and checked before a task is run or reused. A missing required input
marks the task as `invalid-input` and stops the workflow. Required outputs are
checked after successful execution; missing outputs mark the task as
`invalid-output`.

```yaml
tasks:
  - name: run_3dvar
    argv:
      - bash
      - wrappers/jaci/run_mpas_jedi.sh
      - --case
      - "{case_name}"
    cwd: "{project_root}"
    inputs:
      required:
        - wrappers/jaci/run_mpas_jedi.sh
        - "{case_dir}/background.nc"
      optional:
        - "{case_dir}/obs/*.nc4"
    outputs:
      required:
        - "{case_dir}/analysis.nc"
        - "{case_dir}/diagnostics/cost_function.csv"
    input_fingerprint: metadata
```

`inputs.required` and `outputs.required` contain explicit paths; glob patterns
are not accepted. `inputs.optional` accepts optional paths or glob patterns and
may match zero files. Relative artifact paths are resolved from the directory
containing the workflow YAML file.

`input_fingerprint: metadata` records path, size and modification time.
`input_fingerprint: sha256` adds a SHA-256 digest and is appropriate for smaller,
critical inputs. Directories are represented by their recursively listed files.

Required products may also receive small, generic checks:

```yaml
outputs:
  required: ["{case_dir}/analysis.nc"]
  checks:
    - path: "{case_dir}/analysis.nc"
      kind: file
      nonempty: true
      min_size: 1024
```

Scientific validity remains in a versioned program or wrapper and can be an
ordinary task. The runner does not embed NetCDF, GRIB or model-specific rules.

## Context

`context` is a mapping used to render string elements of `argv`, `cwd`, `env`,
PBS values, inputs and outputs using Python-format placeholders. Referencing an
unknown placeholder fails with an explicit error before execution.
Literal braces in an argument use doubled braces (`{{` and `}}`).

`format_version: 1` is recommended in every file. Files from version 0.2 without
this field are read as version 1; explicitly unsupported versions are rejected.

A disabled task is recorded as `skipped` during real execution. A dependent task
is then `blocked`; disabling a prerequisite never silently authorizes downstream
execution. `swf run --dry-run` only renders and validates the planned invocation;
it does not write task state.

## One-time initialization

Cycling workflows may declare tasks that run once before the first scientific
cycle:

```yaml
initialization:
  tasks:
    - name: initialize_model
      argv: [python, initialize.py]
      outputs:
        required: [products/initial-background.nc]
```

Initialization is part of the same logical workflow instance but is not a
scientific cycle. Its task state uses the workflow's no-cycle namespace in
`state.sqlite3`, while ordinary cycling tasks continue to use `(cycle_id, task)`.
This means successful initialization tasks are reused on restart just like any
other successful task: completed steps are not repeated unless their signature
or required products changed, or the user explicitly forces/resets them.

Initialization is strictly ordered before cycle execution. If initialization
fails, no cycle is started. On a later `swf run`, the initialization resumes
from the incomplete task and cycles are released only after it succeeds.

Initialization tasks use the normal task schema and dependency model. Because
they are outside the cycle range, they may omit `cycle_scope` or use only
`cycle_scope: all`; positional selectors such as `first` or `not_last` are not
valid for initialization tasks.

## Cycles

A workflow can declare an inclusive ISO-8601 cycle range. The same structural
task set is executed sequentially for each cycle. All cycles belong to the same
logical workflow instance and the same `.simpleworkflow/state.sqlite3`; task
state is separated by the explicit `cycle_id` dimension.

The existing `start/end/step` form remains supported:

```yaml
cycle:
  start: "2018-04-15T00:00:00Z"
  end: "2018-04-15T18:00:00Z"
  step: PT6H
```

The equivalent duration form is also accepted:

```yaml
cycle:
  start: "2018-04-15T00:00:00Z"
  duration: PT18H
  interval: PT6H
```

Use exactly one of `end` or `duration`, and exactly one of `step` or
`interval`. `step` and `interval` mean the same thing; `step` remains the
name used by the existing `--step` CLI option.

Both endpoints are inclusive. The examples above therefore contain four cycles:
00Z, 06Z, 12Z and 18Z. A range from `2018-04-15T00:00:00Z` through
`2018-04-18T00:00:00Z` at `PT6H` contains 13 cycles. Equivalently,
`duration: PT72H` with `interval: PT6H` also contains 13 cycles.

For every cycle, the following context values are added:

```text
{cycle_time}       2018-04-15T00:00:00Z
{cycle_id}         20180415T000000Z
{cycle_yyyymmddhh} 2018041500
{cycle_year}       2018
{cycle_month}      04
{cycle_day}        15
{cycle_hour}       00

{cycle_index}      0
{cycle_count}      4
{is_first}         true
{is_last}          false

{cycle_is_first}   true
{cycle_is_last}    false
```

Position is zero-based: the first cycle has `cycle_index=0` and the last has
`cycle_index=cycle_count-1`. `is_first` and `is_last` are the preferred
position flags. The older `cycle_is_first` and `cycle_is_last` names remain
available as compatibility aliases.

The immediate neighbours are also available:

```text
{previous_cycle_time}
{previous_cycle_id}
{previous_cycle_yyyymmddhh}
{previous_cycle_year}
{previous_cycle_month}
{previous_cycle_day}
{previous_cycle_hour}

{next_cycle_time}
{next_cycle_id}
{next_cycle_yyyymmddhh}
{next_cycle_year}
{next_cycle_month}
{next_cycle_day}
{next_cycle_hour}
```

For the first cycle all `previous_cycle_*` values are the empty string. For the
last cycle all `next_cycle_*` values are the empty string. Booleans are rendered
as lowercase strings `true` and `false`, matching the string-oriented template
context.

### Cycle selectors

A task normally belongs to every cycle. `cycle_scope` provides a deliberately
small positional selector when a task is meaningful only at a campaign edge:

```yaml
tasks:
  - name: every_cycle
    cycle_scope: all
    argv: [python, all.py, "{cycle_time}"]

  - name: produce_next_cycle_input
    cycle_scope: not_last
    argv: [python, next.py, "{cycle_time}", "{next_cycle_time}"]

  - name: final_summary
    cycle_scope: last
    argv: [python, summary.py, "{cycle_time}"]
```

Supported values are:

- `all` — every cycle; this is the default;
- `first` — first cycle only;
- `not_first` — every cycle except the first;
- `last` — last cycle only;
- `not_last` — every cycle except the last.

There is intentionally no expression language, Python evaluation, or general
`if` syntax. A task that is outside its `cycle_scope` is absent from that cycle;
it is not stored as `skipped`. Dependencies must therefore be structurally
valid for every cycle in which the dependent task itself is active.

### Ordering and restart

Cycle execution is sequential and fail-fast. The complete active task graph for
cycle N must finish successfully before cycle N+1 starts. This deterministic
barrier is what allows a product from one cycle to become an input of the next
without launching cycles concurrently and waiting for files to appear.

A successful task in one cycle is never reused as the success state of another
cycle. If execution stops in the middle of a campaign, a later `swf run` walks
the same ordered cycle range: completed initialization and completed cycles are
reused, the incomplete cycle resumes conservatively, and later cycles run only
after it succeeds.

CLI selection overrides YAML:

```bash
# One explicit cycle
swf run workflow.yaml --cycle-time 2018-04-15T06:00:00Z

# Override a configured range
swf run workflow.yaml \
  --from 2018-04-16T00:00:00Z \
  --to 2018-04-16T18:00:00Z \
  --step PT6H
```

`--cycle-time` may be repeated for multiple specific cycles, but cannot be
combined with `--from`, `--to` or `--step`. When a workflow already declares a
cycle range, an explicitly selected `--cycle-time` retains its original position
in that declared campaign. For example, selecting the middle cycle does not
make it become `first` or `last`; this keeps `cycle_scope` semantics stable for
restart and targeted diagnosis.

## Complete phased example

```yaml
format_version: 1
workflow:
  name: cycling_example

context:
  python: python

initialization:
  tasks:
    - name: initialize
      argv: ["{python}", initialize.py]
      outputs:
        required: [products/background_2018041500.nc]

cycle:
  start: "2018-04-15T00:00:00Z"
  end: "2018-04-15T18:00:00Z"
  step: PT6H

tasks:
  - name: analysis
    argv: ["{python}", analysis.py, "{cycle_time}"]

  - name: forecast
    depends_on: [analysis]
    argv: ["{python}", forecast.py, "{cycle_time}"]

  - name: next_background
    cycle_scope: not_last
    depends_on: [forecast]
    argv:
      - "{python}"
      - background.py
      - "{cycle_time}"
      - "{next_cycle_time}"
```

The YAML describes the process once. Increasing the end date increases runtime
cycle instances in SQLite; it does not duplicate the task definitions.

## State and logs

Without an explicit `--workdir`, task state is stored in
`.simpleworkflow/state.sqlite3` beside the workflow YAML, not relative to the
shell's current directory. One state directory represents one logical workflow
instance.

Successful tasks are skipped only when the previous signature still matches and
declared outputs still exist. Every executed task receives immutable logs and
provenance under `.simpleworkflow/runs/<run-id>/`.

`plan`, `validate`, `status`, `explain` and `run --dry-run` are inspection/planning
operations and do not create state when none exists. `status` and `explain` open
existing state read-only. A full `reset` also clears reusable initialization
state; a reset targeted to selected cycle times leaves initialization intact.
Run and attempt history remain preserved.
