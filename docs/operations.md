# Operations and recovery

## Safe operating model

One `.simpleworkflow` directory represents one logical workflow instance. By
default it lives beside `workflow.yaml` and moves with the scientific case.

```text
case/
├── workflow.yaml
└── .simpleworkflow/
    ├── state.sqlite3
    ├── lock
    ├── logs/
    └── runs/
```

`swf run /path/case/workflow.yaml` therefore uses
`/path/case/.simpleworkflow` even when the command is launched from another
directory. Use `--workdir` only when you deliberately need a different state
location.

One lock protects the workflow state directory from concurrent controllers and
records the computer, process identifier and workflow name for diagnosis.

| State | Meaning | Safe action |
| --- | --- | --- |
| `pending` | Never executed in this workflow/cycle. | Run normally. |
| `running` | The current controller started the task. | Do not start another controller. |
| `success` | The last attempt succeeded and passed reuse checks. | Use `explain` when reuse is unexpected. |
| `failed` | The program returned a failure code. | Read logs, correct the cause and run again. |
| `invalid-input` | A required input was absent. | Restore or correct the input path. |
| `invalid-output` | A required product failed validation. | Inspect the program and product. |
| `skipped` | The task was disabled. | Enable it when downstream work requires it. |
| `stale` | An earlier result became obsolete after upstream repetition. | Let it run again. |
| `blocked` | A dependency has no valid result. | Correct the upstream task first. |
| `interrupted` | The previous controller ended and no activity was found. | Inspect and run again. |
| `unknown` | A process or PBS job may still exist. | Verify it before `reset`. |

`swf explain workflow.yaml` shows reasons, missing files and attempt directories.
`swf validate workflow.yaml` validates without executing scientific programs or
creating persistent state. `swf plan` is also stateless. `--task NAME` selects a
task together with all prerequisites.

## Cycles

Cycles share the same workflow instance and SQLite database. State is maintained
per `(cycle, task)` rather than by inventing another workflow name for each
cycle. This means a completed 00Z cycle and a failed 06Z cycle can coexist in the
same case while preserving one workflow identity.

## Attempt and history records

Every attempt has separate start and final records, stdout, stderr and a SHA-256
checksum for final metadata. Every run stores its effective `workflow.yaml`.
Final metadata is published before successful task state is committed.

The SQLite database also indexes runs and attempts and records state transitions.
`swf reset` clears the current reusable task state for the selected workflow/cycle
but deliberately keeps historical runs, attempts and state events.

Paths below `.simpleworkflow` are stored relatively when possible. Task
signatures represent paths inside the workflow root using a stable workflow-root
token. Moving the whole case therefore keeps restart information usable.

Only a safe technical subset of inherited environment variables participates in
the signature, as hashes rather than clear text. Keep complete environment setup
in a versioned wrapper and never place credentials in workflow YAML.

## Moving or cloning a case

To move an existing execution, move the complete workflow root:

```bash
mv case-A case-B
```

where `case-A` contains both `workflow.yaml` and `.simpleworkflow/`.

Moving only the YAML does not move the execution state. simpleWorkflow does not
maintain a machine-wide registry that tries to rediscover detached state.

Copying the complete root copies the execution history as well. If the copy must
start as a new independent experiment, remove the copied `.simpleworkflow`
before its first run.

## PBS

PBS submission stores the returned job identifier in `scheduler.json`. The
foreground controller consults `qstat -xf`. If a restart cannot prove the job's
situation, it stops at `unknown` instead of submitting a duplicate. Verify
`qsub`, `qstat -xf`, final `Exit_status` and `qdel` on every PBS installation.

Queue-specific modules, placement rules and scientific launch commands belong
in versioned wrappers. Free-form PBS directives are intentionally absent.

## State schema and upgrades

0.4.0 introduces an explicitly versioned state schema. A 0.2.x or 0.3.x database
is never altered as a side effect of `run`, `status`, `reset` or `explain`.
Inspect and migrate it explicitly:

```bash
swf migrate workflow.yaml --check
swf migrate workflow.yaml
```

Migration creates an automatic backup before replacement. If an old database
contains more than one logical workflow, migration stops rather than combining
them silently. See [upgrading to 0.4.0](upgrade-0.4.md) for the complete
procedure, including shared legacy databases and rollback.

## Failure boundaries

SQLite protects state updates. Legacy migration builds the new database
separately and populates it transactionally before an atomic replacement of the
active `state.sqlite3`; the pre-migration database is also preserved as a
backup. Attempt records use temporary files, filesystem synchronization and
atomic publication.

Storage-system failure outside those boundaries still requires the backup and
retention policy of the institution.
