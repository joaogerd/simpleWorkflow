# JOSS submission readiness — working audit (2026-10-13)

This is a preparation checklist, **not a claim of JOSS eligibility**. See the current [author instructions](https://joss.readthedocs.io/en/latest/submitting.html), [paper format](https://joss.readthedocs.io/en/latest/paper.html), and [review criteria](https://github.com/openjournals/joss/blob/main/docs/review_criteria.md).

## Directly observed in the current repository

- [x] Public GitHub repository with source and README.
- [x] OSI-approved MIT license, with LICENSE file.
- [x] Python package metadata and CLI entry points in pyproject.toml (version 0.6.2 at audit time).
- [x] Documented execution semantics, SQLite state/recovery, local/PBS execution, and interactive monitor.
- [x] Pytest, lint, type-checking and coverage configuration in pyproject.toml; **CI execution and actual test results remain to be verified**.
- [ ] Review public commit history, release cadence, third-party issues/PRs and at least six months of demonstrable public development.
- [ ] Check and, where appropriate, add CONTRIBUTING.md and community support/reporting guidance.
- [ ] Independently reproduce installation and tests on supported Python versions.
- [ ] Validate an end-to-end case, including task failure/restart and declared output invalidation.
- [ ] Include a portable scientific demonstration independent of INPE/JACI infrastructure.
- [ ] Document a representative MONAN-JEDI application with public evidence and anonymized example data, if permitted.
- [ ] Obtain external-user feedback, evidence of research use, and citations if available.
- [ ] Verify authorship, affiliations, author approval, funding and ORCID.
- [ ] Verify all bibliography metadata, title, and software comparisons.
- [ ] Fully document generative AI usage in code, documentation, and article, including verification practices.
- [ ] Produce a stable release, archival DOI (e.g. Zenodo), and run the JOSS paper build/check.
- [ ] Check manuscript length (JOSS recommends 750–1750 words) and confirm all required sections are substantive.

## Paper strategy

Primary claim: small, restart-safe, inspectable orchestration for *single-instance scientific workflows*, including sequential local and PBS tasks.

Avoid unsupported claims: superior performance to Cylc/ecFlow/Snakemake; automatic distributed orchestration; independent adoption; broad research impact without evidence.

Suggested research demonstration: reproducible multi-cycle data processing case with (1) YAML definition, (2) dependency graph, (3) intentional failure, (4) restart and reuse decisions, (5) immutable logs/attempt metadata, and (6) a summary of scientifically meaningful generated products.

## Editorial notes

This folder is a working draft. Before submission the paper's claims, author list, references and AI disclosure must be reviewed by the human author(s).
