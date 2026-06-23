# Roadmap

## MVP 0.1.0

Goal: provide a practical local workflow runner for scientific shell pipelines.

Implemented in the MVP branch:

- Python package structure.
- CLI with `run`, `plan`, `status`, and `reset`.
- YAML workflow loader and validation.
- Dependency-based task ordering.
- Local shell execution.
- SQLite state for restart support.
- Per-task stdout/stderr logs.
- Basic MONAN-JEDI and SMNA-inspired examples.

## Next version

Suggested scope for 0.2.0:

- PBS backend with rendered job scripts.
- SLURM backend.
- Cycle expansion for date ranges.
- Better status table output.
- Optional notification hooks.
- CI with unit tests.
- Migration guide from legacy `app/` implementation.
