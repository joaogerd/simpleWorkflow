# Legacy code

The `legacy/app/`, `legacy/unittests/` and `legacy/test/` directories predate the
`simpleworkflow` package introduced in version 0.1.0.

They are retained temporarily as source history only. They are not:

- included in the distributable package;
- executed by the current test suite or CI;
- compatible with the current YAML format;
- supported for new workflows.

In particular, the old YAML examples use free-form `run` and control-flow
constructs such as `while`. The supported package intentionally rejects those
patterns in favor of explicit `argv`, task dependencies, artifact contracts and
cycle expansion.

New development belongs exclusively under `simpleworkflow/`, `tests/`,
`examples/` and `docs/`. Historical code is grouped under `legacy/` so it is not
mistaken for the maintained implementation.
