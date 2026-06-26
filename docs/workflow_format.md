# Workflow format

simpleWorkflow defines dependency-aware tasks that execute explicit program argument vectors. It does not invoke a shell.

## Task fields

Each task must define a unique `name` and a non-empty `argv` list. Each item of `argv` is one exact process argument and supports context placeholders such as `{python}` or `{case_name}`.

Optional execution fields are `depends_on`, `enabled`, `cwd`, `env`, and `executor`.

`cwd` is the task working directory. Relative paths are interpreted from the directory containing the workflow YAML file. `env` is a mapping of task-specific environment values. The only supported executor at this stage is `local`.

The former `run` field is deliberately unsupported. A single command string would require shell parsing and permit implicit redirection, pipelines and environment expansion.

## Artifact contract

Tasks may declare scientific input and output artifacts. Required inputs are rendered and checked before a task is run or reused. A missing required input marks the task as `invalid-input` and stops the workflow. Optional inputs are rendered and glob-expanded, but zero matches are allowed. Required outputs are rendered now; their post-execution validation is added in the next stage.

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

`inputs.required` and `outputs.required` contain explicit artifact paths; glob patterns are not accepted there. `inputs.optional` accepts optional paths or glob patterns and may match zero files. Relative artifact paths are resolved from the directory containing the workflow YAML file.

`input_fingerprint` controls how inputs will be fingerprinted when provenance-aware reuse is enabled. Supported values are `metadata` and `sha256`. The planned default is `metadata`, using path, size and modification time.

## Context

`context` is a mapping used to render string elements of `argv`, `cwd`, `env`, `inputs`, and `outputs` using Python format placeholders.

## Cycles

A workflow can declare an inclusive ISO-8601 cycle range. The same task DAG is executed sequentially for each cycle, with independent workflow state and logs.

```yaml
cycle:
  start: "2018-04-15T00:00:00Z"
  end: "2018-04-15T18:00:00Z"
  step: PT6H
```

For each cycle, simpleWorkflow adds these fields to the task context:

```text
{cycle_time}       2018-04-15T00:00:00Z
{cycle_id}         20180415T000000Z
{cycle_yyyymmddhh} 2018041500
{cycle_year}       2018
{cycle_month}      04
{cycle_day}        15
{cycle_hour}       00
```

Cycle execution is sequential and fail-fast. A successful task in one cycle is never reused as the successful task of another cycle. The effective workflow state and log namespace include the cycle identifier.

CLI selection takes precedence over YAML:

```bash
# One explicit cycle
simpleworkflow run workflow.yaml --cycle-time 2018-04-15T06:00:00Z

# Override the configured range
simpleworkflow run workflow.yaml \
  --from 2018-04-16T00:00:00Z \
  --to 2018-04-16T18:00:00Z \
  --step PT6H
```

`--cycle-time` may be repeated to select multiple specific cycles, but cannot be combined with `--from`, `--to`, or `--step`.

## State and logs

Task status is stored in SQLite under `.simpleworkflow/state.sqlite3` by default. Successful tasks are skipped on subsequent runs unless `--force` is used. Standard output and standard error are stored under `.simpleworkflow/logs/<workflow-name>/`.
