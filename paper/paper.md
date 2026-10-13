---
title: 'simpleWorkflow: A lightweight, restart-safe workflow runner for scientific computing'
tags:
  - Python
  - scientific workflows
  - high-performance computing
  - reproducibility
  - data assimilation
authors:
  - name: João Gerd Zell de Mattos
    affiliation: 1
affiliations:
  - name: National Institute for Space Research (INPE), Brazil
    index: 1
date: 13 October 2026
bibliography: paper.bib
---

# Summary

Scientific experiments frequently involve sequences of programs that must run in a specified order, sometimes across repeated analysis or simulation cycles. Managing these sequences manually can obscure which inputs produced which outputs, complicate recovery after failure, and make experiments difficult to reproduce. **simpleWorkflow** is an open-source Python tool that executes dependency-ordered scientific workflows described in YAML. It supports local commands and a deliberately small Portable Batch System (PBS) execution backend, while persisting task state, immutable attempt records, and operational logs. Researchers can inspect planned execution, explain why tasks are reused or rerun, and monitor runs through a terminal interface without operating a dedicated workflow server.

# Statement of need

Research groups often conduct experiments on shared high-performance computing (HPC) systems where individual applications already provide the numerical algorithms, but researchers still need to connect data preparation, model execution, diagnostics, and post-processing. Ad hoc shell scripts can be sufficient for simple runs, yet become harder to inspect and resume reliably as the number of tasks and cycles grows. A lightweight runner can reduce orchestration overhead for a single scientific case while retaining evidence needed to understand and reproduce a run.

simpleWorkflow targets researchers who want explicit task dependencies and inspectable execution records but do not need a permanently running scheduling service. Its task specifications use argument vectors rather than interpreted shell command strings, and its local state remains alongside the workflow by default. A workflow can be inspected without modifying its persistent state.

# State of the field

Established workflow engines address broader requirements. Cylc supports cycling workflows and long-running orchestration in operational and research environments [@oliver2018cylc]. Other systems, such as Snakemake [@molder2021snakemake], focus on scalable and reproducible data-analysis workflows with rich scheduling and execution capabilities. These are valuable choices when a scientific project needs their broader ecosystems, scheduling capabilities, or advanced workflow semantics.

simpleWorkflow makes a narrower design trade-off: it manages one logical workflow instance through a local state directory, runs dependency-ordered tasks sequentially, and avoids a daemon, distributed controller, or generalized event service. The motivation for building a separate tool is not to replace established engines but to provide a small and inspectable execution model for research cases where maintaining a larger orchestration system would be unnecessary. This scope should not be mistaken for feature or performance superiority over existing systems.

# Software design

Users define tasks and dependencies in a YAML file and invoke a command-line interface to validate, plan, execute, inspect, or reset the workflow. The execution model includes required input and output checks and conservative result reuse: a successful task is reusable only if its signature remains valid and declared outputs pass their checks. Signatures incorporate effective task configuration, relevant environment values, executable identity, and declared input fingerprints.

A SQLite database records workflow state, runs, tasks, cycles, attempts, and transitions. Each execution attempt has its own logs and metadata, while each run preserves its effective workflow definition. This separation enables inspection of historical attempts without overwriting earlier evidence. When external execution outcomes cannot be established confidently, the recovery model distinguishes an unknown result from a demonstrated failure, avoiding unverified automatic repetition.

The PBS backend submits a job, captures its identifier, and waits for its outcome in the foreground. An optional terminal user interface reconstructs workflow state and displays cycles, attempts, logs, and scheduler output from persisted evidence. The interface is not the source of operational truth; closing it does not itself cancel execution. Non-interactive execution remains available for batch environments and continuous integration.

# Research impact statement

The software was developed in the context of scientific workflow requirements arising from atmospheric modeling and data-assimilation experiments, including iterative experiments on HPC infrastructure. Features such as scientific cycle expansion, PBS integration, input/output validation, and per-attempt provenance address requirements common in this setting. The design is domain-independent: tasks can invoke arbitrary scientific executables, and the tool does not embed atmospheric-model logic.

For the final submission, this statement will be supplemented with a public, reproducible scientific case study and verifiable evidence of adoption, use by other researchers, or external feedback. We do not claim benchmarked performance gains or independent adoption without such evidence.

# AI usage disclosure

Generative AI assistance was used to prepare an initial draft of this manuscript. The author is responsible for checking technical descriptions against the source code, validating references, and revising the text prior to submission. The extent of AI assistance used during software development and documentation, and the associated human verification procedures, must be reviewed and documented accurately before submission.

# Acknowledgements

Acknowledgements, funding information, and any additional eligible software authors will be verified and finalized before submission.

# References
