# Persistent state model

Starting with simpleWorkflow 0.4.0, one `.simpleworkflow` directory represents
one logical workflow instance.

```text
case/
├── workflow.yaml
└── .simpleworkflow/
    ├── state.sqlite3
    ├── lock
    ├── logs/
    ├── runs/
    └── backups/
```

The state directory belongs to the workflow. It is not a shared database for
arbitrary YAML files.

## Identity

Each new state database contains one `workflow_instance` row with a generated
UUID. The UUID is an internal identity used for provenance and consistency. It
is not part of the YAML interface and users do not need it to run a workflow.

The absolute path of `workflow.yaml` is not part of persistent identity.
`last_source_path` is only diagnostic metadata and is updated when the state is
opened from a new location.

The source filename is retained as a safety binding. Reusing the same
`.simpleworkflow` explicitly with a different YAML filename is rejected rather
than silently mixing two definitions. Moving a complete case with the same YAML
filename is supported.

## Default location

Without `--workdir`, the state directory is resolved beside the YAML file:

```bash
swf run /work/case/workflow.yaml
```

uses:

```text
/work/case/.simpleworkflow/state.sqlite3
```

It does not depend on the shell's current working directory.

An explicit `--workdir` remains available. A relative explicit path is resolved
from the current directory because the user deliberately supplied it.

`plan` and `validate` do not need persistent runtime state and therefore do not
create `.simpleworkflow`.

## Moving and copying a workflow

Move the workflow root as one unit:

```text
case-A/
├── workflow.yaml
└── .simpleworkflow/
```

becoming:

```text
case-B/
├── workflow.yaml
└── .simpleworkflow/
```

The UUID, task state, cycles, run history and attempt records remain the same.
Paths recorded below `.simpleworkflow` are stored relatively when possible, and
task signatures represent paths inside the workflow root as `$WORKFLOW/...`.
Moving the complete root therefore does not by itself invalidate successful
tasks.

Moving only `workflow.yaml` does not move its state. This is intentional: the
state belongs to the workflow root, not to a globally searchable registry.

Copying the complete root, including `.simpleworkflow`, creates a clone that
contains the same execution history. Removing the copied `.simpleworkflow`
before the first run starts a new workflow instance.

## Cycles

Cycles are not independent workflows. They are a dimension inside one workflow
instance:

```text
workflow_instance
├── cycle 20180415T000000Z
│   ├── task A
│   └── task B
├── cycle 20180415T060000Z
│   ├── task A
│   └── task B
└── cycle 20180415T120000Z
    ├── task A
    └── task B
```

All cycles use the same `state.sqlite3`. `workflow.name` remains the human name
from the YAML; the cycle identifier is stored separately.

## Schema version

The 0.4.0 database is the first simpleWorkflow state database with an explicit
schema version. Application version 0.4.0 starts with:

```text
state schema_version = 1
```

Application version and state schema version are intentionally separate. Future
application releases can keep the same database schema or migrate it explicitly.

The principal tables are:

- `schema_info`: database schema version;
- `workflow_instance`: one logical workflow identity and diagnostic source metadata;
- `cycle_state`: known cycles and their times;
- `task_state`: latest state per `(cycle_id, task)`;
- `state_event`: append-only state transition history;
- `run_history`: indexed workflow runs;
- `attempt_history`: indexed task attempts;
- `migration_history`: source and backup information for legacy migrations.

Detailed per-attempt provenance remains in the inspectable files under `runs/`.
SQLite indexes that history for restart and diagnostics; it does not replace the
human-readable records.

## Reset

`swf reset workflow.yaml` clears the current reusable task state for the selected
workflow/cycle context. Historical `state_event`, `run_history`, `attempt_history`
and filesystem attempt records are preserved.

## Restart safety

A successful task is reused only when its required outputs remain valid and its
current signature matches. Signatures no longer include the simpleWorkflow
package version or the absolute path of the YAML. Paths inside the workflow root
are location-independent.

After migration from older versions, a legacy success is adopted into the new
signature only when available provenance is sufficient to demonstrate semantic
compatibility. Otherwise the task runs again. Uncertainty is resolved in favor
of avoiding unsafe reuse.

PBS recovery remains conservative: a job that cannot be proved finished remains
`unknown` and automatic resubmission is blocked until the user verifies the
scheduler state.
