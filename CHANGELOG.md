# Changelog

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
