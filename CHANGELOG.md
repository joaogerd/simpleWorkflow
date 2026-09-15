# Changelog

## 0.4.0

- Redefine `.simpleworkflow` as the persistent state directory of exactly one
  logical workflow instance.
- Resolve the default state directory beside the workflow YAML rather than from
  the shell's current directory.
- Add an explicit, versioned SQLite schema with workflow instance UUID, cycles,
  task state, state history, runs, attempts and migration history.
- Model cycles explicitly inside one workflow instance instead of encoding them
  into workflow identity.
- Store portable state paths and location-independent task signatures so moving
  the complete workflow root does not itself invalidate restart state.
- Keep `plan` and `validate` stateless; they do not create `.simpleworkflow`.
- Use one workflow lock per state directory.
- Add `swf migrate` and `swf migrate --check` for protected 0.2.x and 0.3.x
  state upgrades.
- Create automatic SQLite backups before migration and replace the active
  database only after successful transactional conversion.
- Detect shared/ambiguous legacy databases and refuse silent merging; support
  explicit extraction of one legacy workflow instance.
- Convert 0.3.x cycle keys into explicit cycle state and preserve available run,
  attempt, status, timestamp and provenance information.
- Reuse migrated successful work only when legacy provenance proves semantic
  compatibility; otherwise rerun conservatively.
- Convert unverifiable 0.2.x `running` tasks to `unknown` rather than assuming
  completion or automatically repeating them.
- Preserve historical state events, runs and attempts across `reset`.
- Add upgrade and state-model documentation for existing scientific campaigns.

## 0.3.0

- Prevent concurrent controllers for the same workflow and work directory.
- Recover interrupted attempts conservatively and represent obsolete, blocked,
  interrupted and uncertain task states explicitly.
- Validate rendered PBS parameters before execution and reject unsafe directive
  values.
- Record PBS job identifiers immediately and wait through foreground `qstat`
  queries.
- Record local process identity, control process groups and support local time limits.
- Publish attempt records atomically, preserve effective YAML and add metadata checksums.
- Include executable and safe inherited-environment identity in task signatures.
- Add recursive directory fingerprints and generic product checks.
- Add `validate`, `explain` and dependency-inclusive task selection.
- Introduce workflow format version 1, correct published examples and group old code
  under `legacy/`.

## 0.2.0

- Add the initial PBS backend, per-attempt provenance and signature-based reuse.

## 0.1.0

- Establish the lightweight local YAML workflow runner.
