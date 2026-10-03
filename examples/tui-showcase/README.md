# simpleWorkflow TUI showcase

These examples exercise the TUI without MONAN, JEDI, PBS or HPC dependencies.

## 1. Minimal

```bash
swf run examples/tui-showcase/01-minimal.yaml --ui tui
```

Expected TUI concepts:

- one workflow;
- one local task;
- stdout;
- task inspector;
- Monitor / Problems / Logs only.

## 2. Standard workflow

```bash
swf run examples/tui-showcase/02-workflow.yaml --ui tui
```

Shows:

- a dependency graph;
- parallel-ready branches;
- stdout and stderr resources;
- a disabled task recorded as skipped;
- successful completion.

## 3. Artifacts and contracts

```bash
rm -rf examples/tui-showcase/demo-work
swf run examples/tui-showcase/03-artifacts.yaml --ui tui
```

Shows:

- context rendering;
- cwd and environment variables;
- required inputs and outputs;
- output checks;
- SHA-256 input fingerprinting;
- immutable attempt resources and logs;
- a skipped optional task.

Run it a second time to see reuse of successful state:

```bash
swf run examples/tui-showcase/03-artifacts.yaml --ui tui
```

Force another execution to create another attempt/run history:

```bash
swf run examples/tui-showcase/03-artifacts.yaml --ui tui --force
```

## 4. Generic campaign

```bash
rm -rf examples/tui-showcase/campaign-work
swf run examples/tui-showcase/04-campaign.yaml --ui tui
```

This is intentionally generic. It represents a batch-processing campaign rather
than a weather or data-assimilation system.

Shows:

- one-time initialization;
- four cycles;
- campaign and cycle navigation;
- cycle context values;
- all useful positional cycle scopes:
  - first;
  - not_first;
  - not_last;
  - last;
  - implicit all;
- per-cycle inputs, outputs and logs;
- campaign summary.

## 5. Problems

```bash
rm -rf examples/tui-showcase/problem-work
swf run examples/tui-showcase/05-problems.yaml --ui tui
```

This workflow intentionally exits with code 7.

Shows:

- completed tasks before a failure;
- a failed task;
- stderr;
- exit code;
- Problems view;
- downstream task not executed because execution is fail-fast.

After the failing run, reopen the persisted state without executing anything:

```bash
swf monitor examples/tui-showcase/05-problems.yaml
```

## Suggested progression

Run the examples in numerical order. They are designed to answer a different
question at each step:

1. What is the minimum useful TUI?
2. What does a normal dependency workflow look like?
3. What does a workflow with real file contracts look like?
4. What does the maximum cycle/campaign interface look like?
5. What does diagnosis of a failure look like?


## 6. Invalid input

```bash
swf run examples/tui-showcase/06-invalid-input.yaml --ui tui
```

Shows a task in `invalid-input` before its process starts.

## 7. Invalid output

```bash
rm -rf examples/tui-showcase/invalid-output-work
swf run examples/tui-showcase/07-invalid-output.yaml --ui tui
```

The process exits successfully but fails the declared output contract, producing
`invalid-output`.

## 8. Blocked dependency

```bash
swf run examples/tui-showcase/08-blocked.yaml --ui tui
```

Shows a disabled prerequisite as `skipped` and its dependent task as
`blocked`.

## 9. Timeout

```bash
swf run examples/tui-showcase/09-timeout.yaml --ui tui
```

Shows a local process terminated by its task timeout and recorded as a failed
attempt with a timeout reason.

## What the showcase covers

Together these examples exercise the main states and surfaces a user can
reasonably produce on a local machine:

- pending;
- running;
- success;
- skipped;
- failed;
- invalid-input;
- invalid-output;
- blocked;
- stdout and stderr;
- exit codes and timeout reasons;
- dependency trees;
- inputs, outputs and validation checks;
- context, cwd and environment variables;
- state reuse and forced re-execution;
- initialization;
- cycles and campaign navigation;
- first / not_first / not_last / last cycle scopes;
- Monitor, Problems, Logs, Cycles and Campaign views.

`stale`, `interrupted`, `unknown` and PBS-specific states depend on restart,
interruption or scheduler conditions rather than a normal deterministic example,
so they are not fabricated by these YAML files.
