# Contributing to simpleWorkflow

Thank you for helping improve simpleWorkflow. We value small, verifiable changes that preserve scientific reproducibility and an inspectable execution model.

## Before opening a pull request

1. Search existing GitHub issues and pull requests to avoid duplicate work.
2. Describe the problem, expected behavior, and how to reproduce it. For behavior changes, discuss backward-compatibility and migration implications.
3. Work in a topic branch based on `develop` (for example, `feature/short-description` or `fix/short-description`). Submit a pull request to `develop`; only validated releases are promoted to `main`.
4. Add a regression test for each bug fix and update user-facing documentation whenever the public behavior or YAML contract changes.
5. Do not merge until CI and relevant reviewer checks have passed. A green CI run does not replace real-cluster validation for PBS behavior.

## Development setup

Python 3.10 or newer is required.

```sh
git clone https://github.com/joaogerd/simpleWorkflow.git
cd simpleWorkflow
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check simpleworkflow tests tools
python -m mypy
```

To run a minimal workflow without an HPC allocation:

```sh
swf plan examples/hello.yaml --color never
swf validate examples/hello.yaml --color never
swf run examples/hello.yaml --ui plain --color never
```

Tests that mock `qsub`, `qstat`, and `qdel` validate control-flow contracts, not a real PBS installation. Label any claimed HPC-specific result with the actual scheduler version and test environment.

## Changes to task and state semantics

The YAML format, task signatures, SQLite schema, restart behavior, and persisted provenance are compatibility-sensitive. Explain whether the change alters any of them. Add tests covering failure, restart and recovery when relevant. Do not introduce shell-command execution in place of explicit `argv` vectors. Keep code for scientific examples out of the generic execution core.

Keep display logic out of persisted state transitions: the TUI is a read-only presentation of operational evidence.

## Reporting bugs and requesting support

Open a GitHub issue with the simpleWorkflow version, operating system and Python version, the sanitized workflow YAML, the exact command, expected and observed results, and a minimal reproduction. For PBS-specific problems, include redacted scheduler responses and command-line details. Never share access tokens, credentials, private research inputs, personal data or confidential cluster paths in a public issue.

Support is community/best-effort; no response-time guarantee is offered. See `SUPPORT.md`.

## Authorship and AI-assisted contributions

Contributions should identify the human responsible for the design, review and verification. If generative AI tools assisted with source, tests or documentation, describe the affected parts and the checks performed in the pull request. Do not submit generated code or citations without human review. Inclusion in a future research paper is based on the scholarly contribution and explicit author agreement, not automatic commit counts.
