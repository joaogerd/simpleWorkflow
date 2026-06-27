# Workflow format

`simpleWorkflow` defines dependency-aware tasks that execute explicit program
argument vectors. It does not parse a shell command language.

## Minimal workflow

```yaml
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
| `enabled` | Optional boolean; disabled tasks are recorded as skipped. |
| `cwd` | Optional working directory, relative to the workflow YAML when not absolute. |
| `env` | Optional mapping of task-specific string environment variables. |
| `executor` | `local` (default) or `pbs`. |
| `pbs` | Required PBS settings when `executor: pbs`; see [PBS execution](pbs.md). |
| `inputs` | Declared input artifact contract. |
| `outputs` | Declared output artifact contract. |
| `input_fingerprint` | `metadata` (default) or `sha256`. |

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
critical file inputs.

## Context

`context` is a mapping used to render string elements of `argv`, `cwd`, `env`,
PBS values, inputs and outputs using Python-format placeholders. Referencing an
unknown placeholder fails with an explicit error before execution.

## Cycles

A workflow can declare an inclusive ISO-8601 cycle range. The same task DAG is
executed sequentially for each cycle, with independent workflow state, logs and
provenance.

```yaml
cycle:
  start: "2018-04-15T00:00:00Z"
  end: "2018-04-15T18:00:00Z"
  step: PT6H
```

For every cycle, these context values are added:

```text
{cycle_time}       2018-04-15T00:00:00Z
{cycle_id}         20180415T000000Z
{cycle_yyyymmddhh} 2018041500
{cycle_year}       2018
{cycle_month}      04
{cycle_day}        15
{cycle_hour}       00
```

Cycle execution is sequential and fail-fast. A successful task in one cycle is
never reused as the success state of another cycle. The effective workflow name
and state namespace include the cycle identifier.

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
combined with `--from`, `--to` or `--step`.

## State and logs

Task state is stored in `.simpleworkflow/state.sqlite3` by default. Successful
tasks are skipped only when the previous signature still matches and declared
outputs still exist. Every executed task receives immutable logs and provenance
under `.simpleworkflow/runs/<run-id>/`.
