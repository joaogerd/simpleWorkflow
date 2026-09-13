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

The remaining work for this version is operational validation on JACI with a
small job and then one MONAN-JEDI smoke case.

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

## Next, only when demonstrated by use

- operational PBS validation on JACI, including interruption and expired job data;
- a similarly small SLURM backend only when a real scientific user requires it;
- narrowly classified retries only after transient failures are identified in practice.

Parallel task execution, scheduler polling daemons, web dashboards, remote
controllers and generalized event processing are intentionally out of scope.
