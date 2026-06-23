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

## State and logs

Task status is stored in SQLite under `.simpleworkflow/state.sqlite3` by default. Successful tasks are skipped on subsequent runs unless `--force` is used. Standard output and standard error are stored under `.simpleworkflow/logs/<workflow-name>/`.
