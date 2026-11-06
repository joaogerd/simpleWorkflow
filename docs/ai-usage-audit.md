# Generative AI use — audit trail

This document is a working transparency log for JOSS preparation. It is **not** a substitute for the required full human-authored `AI usage disclosure` in the submitted paper. The authors must review all earlier project history and certify the final scope.

## Confirmed work in the 6 November 2026 audit

- **Tool/model:** OpenAI ChatGPT, GPT-6 (session model).
- **Scope — software:** assisted source inspection, identification of duplicated template rendering, creation of `simpleworkflow/templates.py`, edits to `engine.py`, `artifacts.py`, `config.py` and `cli.py`, and creation of regression tests `tests/test_config_error_boundary.py` in [PR #71](https://github.com/joaogerd/simpleWorkflow/pull/71).
- **Scope — documentation:** assisted preparation of `CONTRIBUTING.md`, `SUPPORT.md`, `docs/joss-readiness-audit-2026-11.md` and this transparency record in [PR #72](https://github.com/joaogerd/simpleWorkflow/pull/72).
- **Scope — examples:** assisted creation and revision of a standard-library synthetic scientific pipeline, YAML workflow and end-to-end test, with review-driven source input fingerprint and test-isolation corrections in [PR #73](https://github.com/joaogerd/simpleWorkflow/pull/73).
- **Scope — manuscript:** assisted updates to the existing [PR #70](https://github.com/joaogerd/simpleWorkflow/pull/70), strengthening the state-of-the-field comparison, adding and verifying references, and revising the provisional AI disclosure.
- **Automated validation:** [GitHub Actions](https://github.com/joaogerd/simpleWorkflow/actions/runs/42230804864) reported 310 passed tests for each Python 3.10, 3.11, 3.12; Ruff, mypy, package/build and optional TUI smoke checks passed; total test coverage 84.02–84.05%. This is technical evidence, **not** human authorship, human evaluation of scientific impact, or actual PBS-cluster testing.
- **Review and responsibility:** the human maintainer must independently inspect the source diff, validate the changed behavior and approve the final design, scientific framing, authorship and references. Do not claim this human review has occurred before confirmation.

## Information to collect before JOSS submission

1. Any earlier AI assistance in code, design, tests, documentation, and paper authoring: provider, exact model/version (where available), dates and contribution scope.
2. The human authors' record of code review, correction, test validation and technical design decisions.
3. Reference checks and absence of fabricated results, adoption data or experimental claims.
4. Explicit disclosure in `paper/paper.md` that accurately reflects all assistance, not just manuscript drafting.

JOSS's current author policy requires model/version, scope and **human** verification. It also prohibits using generative AI for conversational exchanges with editors and reviewers, except translation assistance. See [JOSS submission policy](https://joss.readthedocs.io/en/latest/submitting.html#ai-usage-policy).
