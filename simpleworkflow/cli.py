from __future__ import annotations

import argparse
import time
from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from .config import load_workflow
from .console import TerminalReporter
from .cycles import CycleContext, resolve_cycle_contexts
from .engine import WorkflowEngine


def _add_cycle_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--cycle-time",
        action="append",
        dest="cycle_times",
        metavar="TIME",
        help="Run one explicit ISO-8601 cycle; repeat this option for multiple cycles.",
    )
    parser.add_argument(
        "--from",
        dest="cycle_start",
        metavar="TIME",
        help="Override cycle.start with an ISO-8601 timestamp.",
    )
    parser.add_argument(
        "--to",
        dest="cycle_end",
        metavar="TIME",
        help="Override cycle.end with an ISO-8601 timestamp.",
    )
    parser.add_argument(
        "--step",
        dest="cycle_step",
        metavar="DURATION",
        help="Override cycle.step with an ISO-8601 duration such as PT6H.",
    )


def _add_display_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="Terminal color mode: auto (default), always or never.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show internal task names, executors and rendered commands.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simpleworkflow",
        description="Lightweight YAML workflow runner for scientific pipelines.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("run", "plan", "status", "reset"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("workflow")
        command_parser.add_argument("--workdir", default=".simpleworkflow")
        _add_cycle_options(command_parser)
        _add_display_options(command_parser)

        if command == "run":
            command_parser.add_argument("--force", action="store_true")
            command_parser.add_argument("--dry-run", action="store_true")

    return parser


def _cycle_engines(
    config: dict[str, Any],
    args: argparse.Namespace,
    reporter: TerminalReporter,
) -> Iterable[tuple[CycleContext | None, WorkflowEngine]]:
    cycles = resolve_cycle_contexts(
        config.get("cycle"),
        cycle_times=args.cycle_times,
        start=args.cycle_start,
        end=args.cycle_end,
        step=args.cycle_step,
    )
    if not cycles:
        yield None, WorkflowEngine(
            config=config,
            workdir=args.workdir,
            force=getattr(args, "force", False),
            dry_run=getattr(args, "dry_run", False),
            reporter=reporter,
        )
        return

    base_name = config.get("workflow", {}).get("name", "workflow")
    for cycle in cycles:
        resolved = deepcopy(config)
        resolved["workflow"] = {
            **resolved.get("workflow", {}),
            "name": f"{base_name}__{cycle.cycle_id}",
        }
        resolved["context"] = {
            **resolved.get("context", {}),
            **cycle.render_context(),
        }
        yield cycle, WorkflowEngine(
            config=resolved,
            workdir=args.workdir,
            force=getattr(args, "force", False),
            dry_run=getattr(args, "dry_run", False),
            reporter=reporter,
        )


def _status_entries(engine: WorkflowEngine) -> list[tuple[str, str]]:
    return [
        (task_name, engine.state.get_status(engine.workflow_name, task_name) or "pending")
        for task_name in engine.plan()
    ]


def _display_workflow_name(config: dict[str, Any]) -> str:
    return str(config.get("workflow", {}).get("name", "workflow"))


def _mode(args: argparse.Namespace) -> str:
    if getattr(args, "dry_run", False):
        return "dry-run"
    if getattr(args, "force", False):
        return "force rerun"
    return "normal"


def _show_header(
    reporter: TerminalReporter,
    *,
    command: str,
    config: dict[str, Any],
    args: argparse.Namespace,
    cycle: CycleContext | None,
    engine: WorkflowEngine,
) -> list[str]:
    plan = engine.plan()
    reporter.workflow_header(
        command=command,
        workflow_name=_display_workflow_name(config),
        workdir=str(args.workdir),
        cycle_time=cycle.cycle_time if cycle is not None else None,
        mode=_mode(args),
        task_count=len(plan),
    )
    return plan


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_workflow(args.workflow)
    reporter = TerminalReporter(color=args.color, verbose=args.verbose)

    if args.command == "plan":
        index = 1
        for cycle, engine in _cycle_engines(config, args, reporter):
            try:
                plan = _show_header(
                    reporter,
                    command="plan",
                    config=config,
                    args=args,
                    cycle=cycle,
                    engine=engine,
                )
                reporter.note("Execution order")
                for task_name in plan:
                    reporter.plan_item(index, task_name)
                    index += 1
            finally:
                engine.state.close()
        return 0

    if args.command == "run":
        for cycle, engine in _cycle_engines(config, args, reporter):
            started = time.monotonic()
            try:
                _show_header(
                    reporter,
                    command="run",
                    config=config,
                    args=args,
                    cycle=cycle,
                    engine=engine,
                )
                result = engine.run()
                if getattr(args, "dry_run", False):
                    elapsed = TerminalReporter._format_elapsed(time.monotonic() - started)
                    reporter.note(
                        f"Dry run complete in {elapsed}. No task state was changed."
                    )
                else:
                    reporter.run_summary(
                        _status_entries(engine),
                        elapsed_seconds=time.monotonic() - started,
                        exit_code=result,
                    )
                if result != 0:
                    return result
            finally:
                engine.state.close()
        return 0

    if args.command == "status":
        for cycle, engine in _cycle_engines(config, args, reporter):
            try:
                _show_header(
                    reporter,
                    command="status",
                    config=config,
                    args=args,
                    cycle=cycle,
                    engine=engine,
                )
                engine.status()
            finally:
                engine.state.close()
        return 0

    if args.command == "reset":
        for cycle, engine in _cycle_engines(config, args, reporter):
            try:
                _show_header(
                    reporter,
                    command="reset",
                    config=config,
                    args=args,
                    cycle=cycle,
                    engine=engine,
                )
                engine.reset()
            finally:
                engine.state.close()
        reporter.note("Workflow state reset.")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
