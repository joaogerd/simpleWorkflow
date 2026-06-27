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
- `qsub -W block=true` submission so task completion retains a simple meaning;
- PBS resource declarations for queue, project, walltime, `select`, `ncpus`,
  `mpiprocs` and OpenMP threads;
- PBS script, scheduler output paths and returned job id in provenance;
- validation that rejects non-blocking PBS submission;
- Ruff, mypy and coverage-oriented development configuration.

The remaining work for this version is operational validation on JACI with a
small job and then one MONAN-JEDI smoke case.

## Next, only when needed

- a similarly small SLURM blocking backend;
- optional retry and timeout policy for transient site failures;
- selective execution of a subset of the DAG;
- clearer blocked/upstream-failure task states;
- a friendly, color-aware terminal renderer for plan, run and status output.

Parallel DAG execution, scheduler polling daemons, web dashboards, remote
controllers and generalized event processing are intentionally out of scope.
