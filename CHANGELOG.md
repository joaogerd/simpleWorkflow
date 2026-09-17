# Changelog

## 0.5.1

simpleWorkflow 0.5.1 refines the professional TUI introduced in 0.5.0 so the
monitor behaves as an operational navigation surface rather than a mostly static
status screen.

- Restore clickable date and cycle navigation inspired by the original
  `ux/professional-terminal` implementation while keeping `MonitorSnapshot` and
  `state.sqlite3` authoritative.
- Show the selected day separately from its cycles and derive the available cycle
  buttons from the persisted/presentation cycles instead of assuming fixed
  00Z/06Z/12Z/18Z schedules.
- Add previous/next date and previous/next cycle controls, with compact cycle
  slots that follow the currently selected part of a longer campaign.
- Make the campaign view operational: group cycles by date, summarize task state
  per day and let a selected campaign row jump back to Monitor at that date.
- Restore task filtering with `/`; matching can use the internal task name,
  compact display label or current task state without changing workflow state.
- Restore a direct Logs action in the Inspector whenever attempt logs are
  available, including a count of available log streams.
- Add explicit log follow/pause behavior so live output can be frozen while it is
  inspected and resumed without leaving the Logs view.
- Add a problem count to the Problems tab while preserving direct navigation from
  a problem to the most useful available error log.
- Keep non-cycle/global tasks in the explicit `Workflow` section and shorten
  unrolled task labels by removing only the already-known cycle identifier from
  presentation text.
- Preserve all 0.5.0 execution boundaries: no engine changes, no state-schema
  changes, no daemon/server, no workflow mutation from the TUI and no change to
  plain/PBS/CI output.

## 0.5.0

simpleWorkflow 0.5.0 combines the persistent 0.4 state model with the
professional interactive terminal monitor.

- Restore the professional full-screen terminal monitor that was developed and
  refined on `ux/professional-terminal`, adapted to the 0.4 persistent-state
  model instead of reviving the legacy state API.
- Add a presentation-independent `MonitorSnapshot` read model over
  `state.sqlite3` so the TUI can reconstruct workflow, cycle, task, run, attempt
  and problem state without owning a second source of truth.
- Add `swf monitor workflow.yaml` for read-only attachment to an existing
  workflow instance, including closing and reopening after state changes that
  happened while no monitor was running.
- Add `swf run --ui auto|tui|plain`; `auto` uses the TUI only on a capable
  interactive terminal with the optional dependencies installed and otherwise
  preserves the traditional `TerminalReporter` output.
- Keep Rich and Textual optional under the `simpleworkflow[tui]` extra so the
  core runner remains lightweight for HPC, PBS, CI and redirected log use.
- Restore the five approved operational views: Monitor, Ciclos, Campanha,
  Problemas and Logs, with a workflow tree, Inspector and compact cycle timeline.
- Read command, working directory, PBS job ID and available stdout/stderr files
  from immutable attempt provenance while keeping SQLite task state authoritative.
- Make attempt-file discovery defensive: absent or incomplete metadata and log
  files reduce the displayed detail rather than breaking the monitor.
- Visualize deliberately unrolled scientific campaigns without changing their
  execution model: explicit `--cycle` metadata creates presentation groups,
  same-cycle gates may inherit a group, and ambiguous/global tasks remain in a
  separate Workflow section.
- Keep native persisted cycles authoritative whenever `cycle_state` exists; the
  unrolled timeline never creates artificial cycle state or rewrites dependencies.
- Add wide/narrow terminal behavior, a compact help overlay, a limited semantic
  palette, `NO_COLOR` handling and symbols that keep state understandable without
  color.
- Define `q` as a presentation action only. Closing the TUI never silently
  cancels a local process or PBS job; an attached run continues to its normal
  result and releases its normal workflow lock afterward.
- Add restart-safe/headless TUI coverage, automatic UI selection tests,
  conservative unrolled-cycle tests, MONAN-JEDI-shaped 50-task coverage,
  persisted problem/log tests and package validation for both core-only and
  `[tui]` installations.
- Build and exercise both wheel and source distribution in CI, including a
  core-only environment with no Textual/Rich and a separate installed TUI
  environment.
- Preserve the 0.4.0 SQLite schema and workflow-engine execution semantics; this
  release introduces no daemon, socket service, web server or centralized
  scheduler and is not a breaking state-format change.

## 0.4.0

- Redefine `.simpleworkflow` as the persistent state directory of exactly one
  logical workflow instance.
- Resolve the default state directory beside the workflow YAML rather than from
  the shell's current directory.
- Add an explicit, versioned SQLite schema with workflow instance UUID, cycles,
  task state, state history, runs, attempts and migration history.
- Model cycles explicitly inside one workflow instance instead of encoding them
  into workflow identity.
- Store portable state paths and location-independent task signatures so moving
  the complete workflow root does not itself invalidate restart state.
- Keep `plan`, `validate`, `status`, `explain` and `run --dry-run` free of
  persistent-state creation; inspect existing state read-only where applicable.
- Use one local workflow lock per state directory for `run`, `reset` and legacy
  migration so state-changing operations cannot overlap.
- Add `swf migrate` and `swf migrate --check` for protected 0.2.x and 0.3.x
  state upgrades.
- Create durable SQLite backups before migration, build the replacement database
  transactionally under a temporary name and install it only with atomic replace.
- Preserve the legacy database and backup if final replacement fails, remove the
  abandoned migration temporary file and allow a later retry.
- Detect shared/ambiguous legacy databases and refuse silent merging; support
  explicit extraction of one legacy workflow instance.
- Convert 0.3.x cycle keys into explicit cycle state and preserve available run,
  attempt, status, timestamp and provenance information.
- Reuse migrated successful work only when legacy provenance proves semantic
  compatibility; otherwise rerun conservatively.
- Convert unverifiable 0.2.x `running` tasks to `unknown` rather than assuming
  completion or automatically repeating them.
- Preserve historical state events, runs, attempts and migration history across
  `reset`, while clearing current reusable task state.
- Reject future state schemas with a clear requirement for a newer
  simpleWorkflow rather than interpreting them optimistically.
- Add upgrade and state-model documentation for existing scientific campaigns.

## 0.3.0

- Prevent concurrent controllers for the same workflow and work directory.
- Recover interrupted attempts conservatively and represent obsolete, blocked,
  interrupted and uncertain task states explicitly.
- Validate rendered PBS parameters before execution and reject unsafe directive
  values.
- Record PBS job identifiers immediately and wait through foreground `qstat`
  queries.
- Record local process identity, control process groups and support local time limits.
- Publish attempt records atomically, preserve effective YAML and add metadata checksums.
- Include executable and safe inherited-environment identity in task signatures.
- Add recursive directory fingerprints and generic product checks.
- Add `validate`, `explain` and dependency-inclusive task selection.
- Introduce workflow format version 1, correct published examples and group old code
  under `legacy/`.

## 0.2.0

- Add the initial PBS backend, per-attempt provenance and signature-based reuse.

## 0.1.0

- Establish the lightweight local YAML workflow runner.
