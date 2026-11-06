# Portable scientific workflow demonstration

This example executes a complete, deterministic three-step synthetic climate-series
analysis using only Python's standard library and simpleWorkflow. It is designed
for **independent functional verification**, without data downloads, credentials,
a scheduler, MONAN, INPE infrastructure or third-party numerical packages.

It is **not** an observational dataset, a scientific validation study, proof of
independent adoption, or evidence that the estimated synthetic trend describes
actual climate change.

## Run

From the simpleWorkflow repository root after installing the package:

```sh
swf plan examples/reproducible-study/workflow.yaml
swf validate examples/reproducible-study/workflow.yaml
swf run examples/reproducible-study/workflow.yaml --ui plain --color never
swf status examples/reproducible-study/workflow.yaml
swf explain examples/reproducible-study/workflow.yaml
```

The workflow creates a deterministic five-year series (60 synthetic monthly
values), removes the estimated calendar-month means, and fits a least-squares
linear trend to those anomalies. Its products appear under
`examples/reproducible-study/data/`:

- `monthly_temperature.csv`: synthetic observations.
- `monthly_anomalies.csv`: anomalies about each calendar-month climatology.
- `trend_summary.json`: sample size, trend estimate and residual RMS.

Every task declares its required inputs and outputs, including `pipeline.py`
as an implementation input, and validates that output files exist and are
nonempty. Running the same workflow again with identical inputs demonstrates
the conservative reuse path; changing the script or data (or applying `--force`)
invalidates reuse and exercises rerun behavior. Runtime logs, attempt provenance and state
are stored in `.simpleworkflow/` next to the workflow definition by default.

The workflow explicitly sets `cwd: "."` so that its relative commands are
resolved from the YAML directory, independent of the shell's launch directory.
To use a different Python executable, change the `context.python` value in
your copy of the YAML.

The example is exercised by `tests/test_scientific_example.py` in CI.
For an actual research-impact dossier, supplement this independent technical
demonstration with a documented, authentic scientific use case and verifiable
research outcomes.
