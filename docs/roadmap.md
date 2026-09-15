# Roadmap

## Design principle

`simpleWorkflow` remains a small, local-first runner for scientific pipelines.
New features are accepted only when they preserve a workflow that a researcher
can install, read and diagnose without operating a workflow service.

## 0.1.0 — local scientific workflow foundation

Implemented:

- Python package and CLI with `run`, `plan`, `status` and `reset`;
- YAML loading and strict task validation;
- dependency-based sequential task ordering;
- explicit `argv` local execution without shell parsing;
- SQLite restart state;
- declared input/output artifact validation;
- deterministic signatures and safe reuse;
- immutable logs and provenance for each execution attempt;
- generic sequential cycle expansion.

## 0.2.0 — blocking PBS execution

Implemented:

- executor contract shared by local and PBS backends;
- one rendered PBS script per task attempt;
- foreground PBS waiting so task completion retains a simple meaning;
- PBS resource declarations for queue, project, walltime, `select`, `ncpus`,
  `mpiprocs` and OpenMP threads;
- PBS script, scheduler output paths and returned job id in provenance;
- validation that rejects non-blocking PBS submission;
- Ruff, mypy and coverage-oriented development configuration.

## 0.3.0 — consistency and recovery

Implemented:

- exclusive execution and conservative interruption recovery;
- explicit `stale`, `blocked`, `interrupted` and `unknown` states;
- atomic attempt records, checksums and effective YAML snapshots;
- early rendered PBS validation and safe directive values;
- immediate PBS job identifiers with foreground status polling;
- local process groups, process records and time limits;
- `validate`, `explain` and dependency-inclusive `--task` selection;
- generic product checks and recursive directory fingerprints;
- format versioning, valid examples, package license and broader quality gates.

## 0.4.0 — one workflow instance per state directory

Implemented for release validation:

- one logical workflow instance per `.simpleworkflow/state.sqlite3`;
- explicit state schema versioning, starting with state schema 1;
- internal stable workflow UUID independent of the YAML absolute path;
- cycle identity as a separate state dimension instead of a modified workflow name;
- default state resolution beside the workflow YAML;
- portable task signatures and relative runtime/history paths for movable cases;
- side-effect-free `plan`, `validate`, `status`, `explain` and `run --dry-run`;
- shared local locking for execution, reset and legacy migration;
- explicit, backed-up migration from 0.2.x and 0.3.x state databases;
- refusal of ambiguous shared legacy databases unless one legacy instance is selected;
- transactional migration into a separate database followed by atomic replacement;
- preservation of run, attempt, state-transition and migration history across reset.

## Next, only when demonstrated by use

- a similarly small SLURM backend only when a real scientific user requires it;
- narrowly classified retries only after transient failures are identified in practice;
- future state-schema migrations only when an actual schema change requires them.

Parallel task execution, scheduler polling daemons, web dashboards, remote
controllers and generalized event processing are intentionally out of scope.
