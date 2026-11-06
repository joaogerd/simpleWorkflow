# simpleWorkflow — technical and JOSS readiness audit

**Audit date:** 6 November 2026  
**Observed refs:** `main` at `b296450e41923db69a29ee7961ed0d1c74481c5e`; `develop` at `fa8b961e34d9b867da008572b5b22e2e617709fa`.  
**Status:** Evidence-based preliminary static and CI-history audit, **not** a claim of complete code review, successful independent installation, HPC validation, or editorial eligibility.

Official references: [submission](https://joss.readthedocs.io/en/latest/submitting.html), [criteria](https://joss.readthedocs.io/en/latest/review_criteria.html), [checklist](https://joss.readthedocs.io/en/latest/review_checklist.html), [paper format](https://joss.readthedocs.io/en/latest/paper.html).

## A. Executive diagnosis

simpleWorkflow is already a nontrivial scientific workflow runner: Python package and two CLI entry points, explicit-argument YAML task definitions, dependency ordering, SQLite persistence, signatures and per-attempt provenance, local and foreground PBS execution, conservative recovery, cycles, and an optional read-only Textual TUI. A CI workflow includes pytest across Python 3.10–3.12, Ruff, mypy, coverage with a 75% minimum threshold, package builds, wheel installation and smoke tests.

The main risk is **scientific/editorial evidence**, followed by compatibility-sensitive contract semantics. The tool is intentionally smaller than server-based workflow orchestrators. It does **not** provide a native SLURM backend, distributed execution, or a daemon. Do not advertise these.

Historical GitHub Actions show successful test jobs on `develop` (13 October 2026). This is evidence of CI execution, not proof of a real PBS cluster run or complete portability. The development branch is 127 commits ahead of `main`; it must be audited independently rather than presumed equivalent to stable code.

## B. Architecture and separation of concerns

| Responsibility | Current modules | Assessment / action |
|---|---|---|
| Input configuration and validation | `config.py`, `cycles.py` | Strict YAML contract largely present; template and error consistency identified in issue #35 |
| Planning and workflow lifecycle | `engine.py`, `lifecycle.py`, portions of `cli.py` | Lifecycle vocabulary is centralized; engine still coordinates multiple responsibilities |
| Local and HPC execution | `executor.py`, `pbs.py` | Local and blocking PBS are the advertised backends; retain subprocess boundaries |
| Persistence and migrations | `state.py`, `migrations.py`, `runs.py`, `locking.py` | Durable SQLite state, explicit recovery; test concurrent and interrupted scenarios |
| Artifact contract and provenance | `artifacts.py`, `signature.py`, `provenance.py` | Required-output ambiguity in issue #34; do not change contracts silently |
| Monitoring | `monitor.py` | Read-only snapshots from persisted state; good separation from execution |
| Presentation | `tui.py`, `tui_inspector.py`, `tui_resources.py`, `tui_viewer.py`, `console.py` | Presentation layer is separate but large; split only if demonstrable maintenance/test benefit |

Indicative size on `develop`: `engine.py` ~867 lines, `state.py` ~953, `monitor.py` ~740, `cli.py` ~650 and `tui.py` ~2034. Large modules require targeted responsibility analysis, not automatic rewrites. A dependency-graph scan and critical-path tests remain necessary before declaring full architectural compliance.

The focused proposed fix in [PR #71](https://github.com/joaogerd/simpleWorkflow/pull/71) introduces an infrastructure-neutral template renderer shared by orchestration and artifact handling, preserving `engine.render_template` as a compatibility alias. This change was merged into `develop` as commit `14b2c3cc7383e774741544ce939fdd591232d27d` after green CI; it has not yet been promoted to stable `main`.

## C. Audited issues and disposition

| Severity | Location | Evidence / impact | Status | Action and acceptance |
|---|---|---|---|---|
| P1 | `artifacts.py` vs `engine.py` | Artifact interpolation used direct `str.format`, while engine converted missing placeholders into `ValueError`; user-visible inconsistency | Fixed in `develop` (PR #71); not released on `main` | CI green, malformed templates raise consistent configuration diagnostics |
| P1 | `config.py` | `version != 1` accepts YAML boolean true and float 1.0 under Python equality | Fixed in `develop` (PR #71); not released on `main` | Reject noninteger versions while accepting integer 1 |
| P1 | `config.py`, `cli.py` | Malformed YAML and some expected OS/SQLite faults were not normalized to concise CLI errors | Fixed in `develop` (PR #71); not released on `main` | Tests prove default concise output and `--debug` tracebacks |
| P1 | `config.py`, `artifacts.py`, `engine.py` | `outputs.checks` can require undeclared outputs, unlike planning dependency-product model | Open [#34](https://github.com/joaogerd/simpleWorkflow/issues/34) | Define single contract; migration notice for existing YAML; end-to-end tests |
| P2 | state and inspector resource paths | Resources after moving workflow root need explicit portability guarantees | Open [#37](https://github.com/joaogerd/simpleWorkflow/issues/37) | Relocation tests of state, logs, attempts and viewer |
| P2 | invalid-input persistence | Invalid-input reasons are not always inspectable from persisted monitoring state | Open [#36](https://github.com/joaogerd/simpleWorkflow/issues/36) | Persist actionable reason and test explain/monitor |
| P2 | scientific examples and documentation | Domain examples exist but are not independent proof of real scientific adoption | Open [#38](https://github.com/joaogerd/simpleWorkflow/issues/38) | Publish reproducible case and validated research-use evidence |
| P3 | PBS logging, TUI | Potential polling noise, UX resilience issues recorded by maintainers | Open [#39](https://github.com/joaogerd/simpleWorkflow/issues/39), [#40](https://github.com/joaogerd/simpleWorkflow/issues/40) | Demonstrate operational value with tests, no cosmetic rewrites |
| Editorial blocker | public history and impact evidence | Current public-development timeline and external use evidence not yet sufficient to assert a JOSS pass | Open | Evidence dossier reviewed against 2026 JOSS gates |
| Editorial blocker | support and contribution instructions | `main`/`develop` did not contain `CONTRIBUTING.md` or `SUPPORT.md` at snapshot | Draft in documentation PR | Merge after review, ensure links are discoverable from README |

**Important:** Existing GitHub issues are leads for verification, not independent proof of every alleged failure. The first three rows have additional directly inspected code evidence.

## D. Changes actually made during this audit

- [PR #71](https://github.com/joaogerd/simpleWorkflow/pull/71) (merged into `develop`; not in stable `main`): `templates.py`, `engine.py`, `artifacts.py`, `config.py`, `cli.py`, and `tests/test_config_error_boundary.py`. Do not call this merged or validated until workflow checks complete.
- [PR #72](https://github.com/joaogerd/simpleWorkflow/pull/72), merged into `develop` at `61017f6c`: `CONTRIBUTING.md`, `SUPPORT.md`, `README.md`, this audit, and an [AI-assistance log](ai-usage-audit.md). They are not yet part of stable `main`.
- The pre-existing [PR #70](https://github.com/joaogerd/simpleWorkflow/pull/70) (draft; base `main`) contains `paper/paper.md`, `paper/paper.bib`, and `paper/JOSS_READINESS.md`. Revise and reconcile it after technical work; do not create a second conflicting paper.
- [PR #73](https://github.com/joaogerd/simpleWorkflow/pull/73), merged into `develop` at `de229c2f`: a deterministic and scheduler-free [scientific software demonstration](../examples/reproducible-study/README.md), YAML DAG, source-code input signatures, isolated test fixture and end-to-end regression test. Automated review found two issues before merge; both were corrected and the discussions resolved.
- No changes made to `main`, scheduler-specific runtime behavior or the SQLite schema in this audit.

## E. Testing baseline and validation boundaries

Static configuration: Python >=3.10, PyYAML >=6, optional Rich/Textual for TUI, tests via pytest, coverage floor 75%, Ruff, mypy. GitHub CI also builds wheel and sdist and exercises clean core/TUI installation. A successful develop workflow exists: [13 October 2026](https://github.com/joaogerd/simpleWorkflow/actions/runs/38410826320).

Needed evidence before a release:

1. Record complete CI job conclusions on candidate commit, not only workflow existence.
2. Measure actual statement/branch coverage and identify untested code branches; 75% configured is a threshold, not a measured result.
3. Smoke-test installation and a full example independently on Linux and declared Python versions.
4. Exercise YAML validation, artifact paths, restart after success/failure, interrupted processes, stale dependency propagation and state migrations.
5. Verify PBS integration on an actual representative cluster; mock `qsub`/`qstat`/`qdel` only proves adapter behavior under simulated responses.
6. Verify read-only TUI, narrow terminals, crash/restart and provenance consistency.
7. Publish exact commands, environment/commit SHA, results and failure reports. Never claim HPC validation unless independently executed.

### Verified CI outcomes for the audit change (6 November 2026)

The exact PR #71 head commit `cf915d118cdbfd8edb1155cc601faeab6f3aa8f2` passed all five jobs on [GitHub Actions PR run 42230804864](https://github.com/joaogerd/simpleWorkflow/actions/runs/42230804864):

| Environment | Result | Measured total coverage |
|---|---|---|
| Python 3.10 | 310 passed | 84.05% |
| Python 3.11 | 310 passed | 84.05% |
| Python 3.12 | 310 passed | 84.02% |
| Quality checks | Ruff and mypy passed | mypy: no issues in 24 source files |
| Packaging | Wheel, sdist, isolated core/TUI installation and render smoke tests passed | Not a real HPC scheduler test |

These are independently executed CI results retrieved from completed job logs, not local claims or a scientific compute benchmark. PR #71 was reviewed against its diff and merged into `develop` as `14b2c3cc7383e774741544ce939fdd591232d27d`. This commit has not been promoted to stable `main`.

### Verified independently reproducible example

[PR #73](https://github.com/joaogerd/simpleWorkflow/pull/73) passed all five GitHub Actions jobs on the corrected head commit `979081784d0ed4a3b990f20a638149d1621cde3c`: **311 passed** on Python 3.10, 3.11 and 3.12, with **84.05% measured total coverage** in each environment. [CI run](https://github.com/joaogerd/simpleWorkflow/actions/runs/42234276681).

The new `examples/reproducible-study/` uses only the standard library, explicitly declares `pipeline.py` as a required input for each task, generates deterministic synthetic monthly temperatures, computes anomalies and an ordinary least-squares trend, and tests that modifying the scientific implementation invalidates previous reusable results. Its integration test isolates generated `data/` and `.simpleworkflow/` directories. Automated review identified these two issues, and they were corrected before merge.

**Scope limitation:** the existing `examples/monan_jedi_3dvar.yaml` and `examples/smna_gsi_bam.yaml` refer to external institutional scripts/configuration that are not bundled here; they document integration patterns but are not independently executable scientific demonstrations. The new synthetic case provides independent **software** reproducibility, not evidence of external research adoption and not the larger failure/restart/cycle validation still planned for study A.

### Direct-import architecture inventory

A static scan of top-level relative imports in the 23 Python modules of the `develop` package identified no direct import cycle in the observed dependency list. The greatest direct importer is `engine.py` (10 dependencies: artifacts, console, executor, lifecycle, locking, pbs, provenance, runs, signature, state), followed by `cli.py` (6), `tui.py` (5) and `monitor.py` (3). This is evidence that coarse module boundaries are presently acyclic; it does **not** prove dependency inversion, dynamic imports, full SoC compliance or all functional paths. `engine.py` and `tui.py` deserve focused cohesion review, not arbitrary splitting.

## F. JOSS readiness matrix

| Criterion | Rating | Evidence and needed action |
|---|---|---|
| Public, browsable source and issue tracker | **Met** | Public GitHub repo with issues and PRs |
| OSI-approved LICENSE file | **Met** | MIT `LICENSE` in repo |
| Installation/package infrastructure | **Partially met** | pyproject + CI build; independent install still required |
| CI, tests and documented functionality | **Partially met** | Extensive tests and green CI snapshots; real-cluster and end-to-end audit pending |
| Open development workflows | **Partially met** | Many PRs/issues; core contributor largely single account and public community feedback unclear |
| Sustained public development across >=6 months | **Not demonstrated** | Repo created Jan 2024, but main history has 2 Jan-2024 commits, 47 Jun-2026, 257 Sep-2026 and 56 Oct-2026 commits; July/Aug 2026 have no commits on this sampled main history. A repo age is not sustained activity |
| Research use / demonstrated impact | **Not verifiable** | Atmospheric modeling examples and design motivation exist; reproducible research use, artifacts, adopter feedback or publications must be collected |
| Generic scientific usefulness and scope | **Partially met** | Domain-neutral YAML engine; explicit reuse case and why not use Nextflow/Snakemake/ecFlow/Cylc still needed |
| CONTRIBUTING and support | **Partially met** | Both added and linked on `develop` in merged PR #72; stable `main` awaits release promotion |
| Release and long-term archive | **Partially met** | Tagged release `v0.6.1` visible; `main` code version 0.6.2 but release publication and DOI not verified |
| JOSS-format paper and bibliography | **Partially met** | Draft PR #70; full reference verification, build and review pending |
| Research impact statement | **Partially met** | Section present as provisional text; evidence incomplete |
| Full AI usage disclosure | **Partially met** | Draft paper discloses assistance for manuscript only; code/docs use, model versions and human validation must be documented fully |
| Author/funding verification | **Not verifiable** | Draft metadata exists; confirm all contributors, affiliations, funding and approval |

JOSS eligibility is an editorial judgement. The above is a conservative audit assessment, not a promise of desk-review acceptance. Current JOSS guidance explicitly treats sustained public history, research impact and open practices as pre-review gates.

## G. State of the field and scientific positioning

| Alternative | Typical scope | Relevant distinction |
|---|---|---|
| [Snakemake](https://www.snakemake.org/) | Rule/file-based DAG, scalable compute, software environments, profiles/executors | Much broader dependency and runtime ecosystem than simpleWorkflow |
| [Nextflow](https://nextflow.io/) | Dataflow DSL, executor separation, local/HPC/cloud portability | Supports PBS **and SLURM**, containers and distributed execution; do not claim equivalent portability |
| [Cylc](https://cylc.github.io/) | Recurrent/cyclic operational workflow orchestration | More appropriate for complex long-lived cycling operations |
| [ecFlow](https://ecflow.readthedocs.io/) | Client/server, stateful operational suites, dependencies and restart | Mature operational scheduler; simpleWorkflow trades orchestration breadth for local simplicity |
| [Parsl](https://parsl-project.org/) | Python-native parallel tasks and execution providers | Distinct Python programming model and parallel execution focus |

A defensible prospective statement is: **simpleWorkflow provides a deliberately bounded, auditable, daemon-free orchestration model for a single scientific workflow instance with explicit commands, conservative reuse/recovery, persistent attempt-level provenance, and a read-only terminal monitor**.

This is a scope/design proposition, not demonstrated superiority or wholly novel algorithm. To make it compelling for JOSS, publish a matrix of *documented capabilities*, a usable example, and the circumstances in which the smaller tool is preferable. The reader should also be told when to select a more established system.

## H. Paper structure

Reuse [PR #70](https://github.com/joaogerd/simpleWorkflow/pull/70).

**Working title:** *simpleWorkflow: A lightweight, restart-safe workflow runner for scientific computing*.

**Central claim:** scientists can manage modest sequential, dependency-aware experiments without a dedicated orchestration service while retaining per-attempt evidence and conservative restart semantics.

Sections required by the current JOSS format: Summary (non-specialist), Statement of need, State of the field (with explicit build-versus-contribute case), Software design (trade-offs), Research impact statement (real evidence), AI usage disclosure (full identification/scope/human review), Acknowledgements and References. JOSS's recommended length is 750–1750 words, not a full-length research paper.

**Study A:** portable synthetic multi-cycle workflow with publicly licensed inputs, deliberate failure, rerun, output validation and inspectable attempt artifacts. **Study B (conditional):** real scientific pipeline using simpleWorkflow, e.g. atmospheric-model/data-assimilation pre- or post-processing, with provenance and permitted datasets. Never present YAML examples alone as evidence of operational use.

**Authors:** confirm all substantive human software contributors and their affiliations; do not treat automated Git author statistics as authorship decisions. **AI disclosure:** record versions, which code/docs/paper were assisted, and precise human test/review steps. Do not use AI to converse with JOSS editors/reviewers except permitted translation assistance.

## I. Evidence-gated weekly schedule

Times are *planning estimates*, not measured work durations. W1 starts Monday 9 November 2026; the year-end break is not counted as an active engineering week. P0 = submission gate, P1 = functional risk, P2 = supporting quality.

| When | Work / priority | Depends on | Effort | Owner | Verifiable completion |
|---|---|---|---|---|---|
| W1 (9–15 Nov) | Confirm baseline SHA, CI and module/issue map; verify PR #71 / P1 | develop head | 6–10 h | maintainer + engineering reviewer | Green PR checks or recorded failures, targeted tests |
| W2 (16–22 Nov) | Resolve output-contract #34, publish migration notes / P1 | W1 | 10–18 h | maintainer | Compatibility test matrix, agreed YAML semantics |
| W3 (23–29 Nov) | Investigate #36 and #37, add recovery/path tests / P1–P2 | W2 | 12–18 h | engineering reviewer | Reproducible failure+fix records, no regressions |
| W4 (30 Nov–6 Dec) | Finish code/SoC checks and test blind spots / P1 | W1–W3 | 12–20 h | maintainer | Reviewed dependency map and regression report |
| W5 (7–13 Dec) | Full local runner + read-only TUI verification / P1 | W4 | 8–12 h | independent tester | Installation and example logs, Python matrix |
| W6 (14–20 Dec) | Actual PBS cluster validation, release candidate decision / P0 | W4–W5, HPC allocation | 8–16 h | HPC operator | Redacted, reproducible scheduler evidence and RC criteria |
| W7 (4–10 Jan 2027) | Portable scientific study A / P0 | W5 | 10–16 h | researcher | Versioned data, YAML, outputs, restart traces |
| W8 (11–17 Jan) | Scientific study B and research-use dossier / P0 | permission/data access | 12–24 h | researcher + HPC collaborators | Links or verifiable private evidence for editors |
| W9 (18–24 Jan) | Independent user evaluation, usability fixes / P0–P2 | W7–W8 | 8–14 h | external researcher | Reproducible feedback, corresponding issues |
| W10 (25–31 Jan) | Documentation, API/use-case tutorial and support pathways / P1 | W7–W9 | 8–16 h | maintainer + writer | Fresh-install tutorial checked by independent user |
| W11 (1–7 Feb) | State-of-field literature and capability comparison / P0 | W8–W10 | 8–12 h | scientific lead | Verified BibTeX, defensible build-vs-contribute rationale |
| W12 (8–14 Feb) | Revise JOSS draft and full AI disclosure / P0 | W11 | 10–16 h | all human authors | 750–1750-word compliant paper and signed-off disclosure |
| W13 (15–21 Feb) | Final scientific and editorial review / P0 | W8, W12 | 6–10 h | independent reviewers | JOSS checklist completed with linked evidence |
| W14 (22–28 Feb) | Release candidate, provenance archive plan / P1 | green CI, real HPC test | 6–10 h | release maintainer | Versioned release, changelog, rollback instructions |
| W15 (1–7 Mar) | Verify >6 months sustained public practice and research impact / P0 | continued public work since 2026 | 4–8 h | maintainer + scientific lead | Evidence gate reviewed; no inflated dates |
| W16 (8–14 Mar) | Submission only if all JOSS gates pass / P0 | W13–W15 | 3–6 h | corresponding author | JOSS paper build, metadata and formal submission |

**Critical path:** reliable runtime contracts → real execution and independent reproduction → actual scientific research-use evidence → public-development/impact gate → manuscript validation → submission.

**Blocking dependencies:** real PBS access, permitted research case/data, sufficient public development history, human authorship and funding confirmation, full AI disclosure, and editorial significance. The March 2027 window is **conditional**, not a guaranteed or scheduled submission date. Continued public iteration may have to extend beyond March if JOSS's six-month expectation is not convincingly demonstrated.

The DOI should be coordinated with the actual release/version and JOSS archival step; do not cite a nonexistent DOI.

**AI provenance for this audit:** See [the AI assistance audit trail](ai-usage-audit.md) for the 6 November 2026 GPT-6 use in source changes, regression tests and documentation, CI evidence, and the explicitly pending human review. Do not assume earlier software development was free of AI assistance.

## J. Next actions by responsibility

**Automatable now:** CI regression triage, static dependency scans, regression-test additions, source/docs consistency review, reference metadata verification, paper-format checks, release-package smoke tests, and reproducibility artifact capture.

**Requires human or external evidence:** real research adoption, public scientific case permissions, genuine HPC testing, design trade-off approval, independent usability trial, scholarly author selection, funding disclosure, model/version AI audit and correspondence with JOSS.

**Release policy:** merge feature fixes to `develop` only after CI and review; promote to `main` after integrated acceptance testing and reproducibility checks. Preserve all history; never force-push protected branches to manufacture a smoother development narrative.
