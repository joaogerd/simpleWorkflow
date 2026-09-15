# Upgrading existing workflows to simpleWorkflow 0.4.0

simpleWorkflow 0.4.0 changes the persistent state model. Existing 0.2.x and
0.3.x databases are supported through an explicit migration command; they are
never modified implicitly by `run`, `status`, `reset` or `explain`.

## What changed

Before 0.4.0, one SQLite database could contain multiple workflow keys. In
0.3.0 those keys could include the absolute YAML path indirectly through a
hash, and cycles were represented by modified workflow names.

Starting with 0.4.0:

> one `.simpleworkflow` directory represents one logical workflow instance.

Cycles, tasks, runs and attempts are dimensions/history inside that instance.

## Important workdir change

0.2.x and 0.3.x defaulted `--workdir .simpleworkflow` relative to the current
shell directory. 0.4.0 defaults to `.simpleworkflow` beside the workflow YAML.

If your old state is already beside the YAML:

```text
case/
├── workflow.yaml
└── .simpleworkflow/state.sqlite3
```

no path adjustment is needed.

If the old state lives somewhere else because the workflow was launched from a
different directory, either move the complete `.simpleworkflow` directory beside
the YAML or pass it explicitly while inspecting and migrating:

```bash
swf migrate /work/case/workflow.yaml \
  --workdir /old/launch/directory/.simpleworkflow \
  --check
```

Continue using the same explicit `--workdir` unless you subsequently move the
entire state directory beside the YAML.

## Step 1: inspect without changing anything

```bash
swf migrate workflow.yaml --check
```

Typical output identifies one of:

- current versioned state;
- legacy `0.2.x` state;
- legacy `0.3.x` state;
- more than one legacy logical workflow in the same database;
- an unknown format that simpleWorkflow will not modify.

`--check` is read-only and does not create a backup or replace the database.

## Step 2: migrate a single unambiguous workflow

```bash
swf migrate workflow.yaml
```

Before replacement, simpleWorkflow creates a SQLite backup below:

```text
.simpleworkflow/backups/
```

with a name such as:

```text
state-v0-2-x-before-migration-20260915T003000Z.sqlite3
```

or:

```text
state-v0-3-x-before-migration-20260915T003000Z.sqlite3
```

The new database is built separately, populated in a transaction, closed and
then atomically replaces `state.sqlite3`. The original database is therefore not
partially rewritten in place.

Running `swf migrate` again on the already current schema is a protected no-op.

## Step 3: verify

```bash
swf status workflow.yaml
swf explain workflow.yaml
```

For a cyclic workflow, optionally inspect an explicit cycle:

```bash
swf status workflow.yaml --cycle-time 2018-04-15T06:00:00Z
```

Then continue normally:

```bash
swf run workflow.yaml
```

## What is preserved

When present in the legacy state/provenance, migration preserves or reconstructs:

- current task status and return code;
- task signature;
- update timestamp;
- failure/recovery reason from 0.3.x;
- attempt path from 0.3.x;
- cycle identity encoded by 0.3.x workflow keys;
- filesystem run records under `runs/`;
- task attempt records under `runs/`;
- available signature payloads from attempt metadata;
- run and attempt history indexes in the new SQLite database;
- a migration record identifying the legacy source and backup.

The existing `runs/` files are not destroyed or rewritten during migration.

## Restart behavior

### Successful tasks

A migrated `success` is not blindly trusted. If legacy attempt provenance is
sufficient to show that the current task, inputs and relevant execution identity
are still equivalent, simpleWorkflow adopts the result into the new portable
signature and reuses it.

If that proof is unavailable, the status/history is still preserved but the task
is rerun when necessary. This is intentionally conservative.

### Failed tasks

A legacy `failed` task remains failed after migration and is eligible to run
again normally after the cause is corrected.

### 0.2.x tasks left as `running`

0.2.x did not store enough process/scheduler information to safely determine
whether an old `running` activity still exists. Migration converts such a state
to `unknown`. Verify the old activity/products before using `reset`.

### 0.3.x interrupted/PBS work

0.3.x attempt directories can contain `process.json`, `scheduler.json`,
`started.json` and final `metadata.json`. These records are retained. The 0.4
restart logic remains conservative and will not knowingly duplicate an uncertain
PBS job.

## Cyclic workflows from 0.3.x

0.3.x could encode a cycle in keys similar to:

```text
forecast__20180415T000000Z@012345abcdef
forecast__20180415T060000Z@012345abcdef
```

Migration groups keys with the same legacy path digest and base workflow name
into one logical workflow instance and converts the timestamps into explicit
cycle rows. Completed cycles can therefore remain completed while later cycles
continue.

## Shared legacy databases: do not merge them

A 0.2.x or 0.3.x database may genuinely contain more than one logical workflow.
0.4.0 will not collapse those records into one instance.

Inspection shows the available legacy instances:

```bash
swf migrate workflow.yaml --check
```

If there is more than one, normal migration stops without making a backup or
changing the database.

To extract one instance safely, first make a complete copy of the legacy
`.simpleworkflow` directory for each workflow root that needs to survive. Then
run migration in each copy with the selector reported by `--check`:

```bash
swf migrate workflow.yaml --legacy-workflow 'forecast@012345abcdef'
```

Only the selected instance becomes the active 0.4 database in that copy. The
automatic backup still contains the complete original shared database, including
all other legacy workflow records.

Do not repeatedly select different legacy workflows against the same already
migrated `state.sqlite3`; after the first successful migration it is, by design,
a single-workflow 0.4 database.

## Recovering the old database

Do not restore state while a `swf run` process is active.

Locate the backup created by migration:

```bash
ls -ltr .simpleworkflow/backups/
```

Preserve the current migrated database before rollback:

```bash
cp .simpleworkflow/state.sqlite3 .simpleworkflow/state.sqlite3.after-migration
```

Restore the selected backup:

```bash
cp .simpleworkflow/backups/state-v0-3-x-before-migration-*.sqlite3 \
   .simpleworkflow/state.sqlite3
```

That restores the legacy SQLite state. A 0.4 command that needs state will again
request migration; use the corresponding old simpleWorkflow release if the goal
is to operate directly on the restored legacy database.

The filesystem `runs/` history is not removed by migration, so keep it together
with the database when archiving or moving an experiment.

## 0.2.x checklist

```bash
# Inspect
swf migrate workflow.yaml --check

# Migrate (automatic backup is created)
swf migrate workflow.yaml

# Verify
swf status workflow.yaml
swf explain workflow.yaml

# Continue
swf run workflow.yaml
```

Expect old `running` records to become `unknown` unless later provenance is
sufficient to reconcile them.

## 0.3.x checklist

```bash
# Inspect legacy keys/cycles
swf migrate workflow.yaml --check

# Migrate
swf migrate workflow.yaml

# Verify one or more cycles
swf status workflow.yaml
swf status workflow.yaml --cycle-time 2018-04-15T00:00:00Z

# Continue the campaign
swf run workflow.yaml
```

If `--check` reports multiple logical instances, follow the shared-database
procedure above instead of forcing them into one state.
