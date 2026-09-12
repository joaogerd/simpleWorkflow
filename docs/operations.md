# Operations and recovery

## Safe operating model

One `swf run` process controls one named workflow in one work directory. A lock
prevents a second controller from executing the same workflow concurrently and
records the computer and process identifier for diagnosis.

| State | Meaning | Safe action |
| --- | --- | --- |
| `pending` | Never executed here. | Run normally. |
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
`swf validate workflow.yaml` validates without executing scientific programs.
`--task NAME` selects a task together with all prerequisites.

## Attempt records

Every attempt has separate start and final records, stdout, stderr and a SHA-256
checksum for final metadata. Every run stores its effective `workflow.yaml`.
Final metadata is published before successful state is committed.

Only a safe technical subset of inherited environment variables participates in
the signature, as hashes rather than clear text. Keep complete environment setup
in a versioned wrapper and never place credentials in workflow YAML.

## PBS

PBS submission stores the returned job identifier in `scheduler.json`. The
foreground controller consults `qstat -xf`. If a restart cannot prove the job's
situation, it stops at `unknown` instead of submitting a duplicate. Verify
`qsub`, `qstat -xf`, final `Exit_status` and `qdel` on every PBS installation.

Queue-specific modules, placement rules and scientific launch commands belong
in versioned wrappers. Free-form PBS directives are intentionally absent.

## Failure boundaries

SQLite protects state updates, while attempt records use temporary files,
filesystem synchronization and atomic publication. Storage-system failure still
requires the backup and retention policy of the institution.
