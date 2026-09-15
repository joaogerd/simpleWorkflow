from __future__ import annotations

import argparse
import os
import sys
import traceback
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any

from .config import load_workflow
from .console import TerminalReporter, WorkflowReporter
from .cycles import CycleContext, resolve_cycle_contexts
from .engine import WorkflowEngine
from .migrations import MigrationError, StateInspection, inspect_state, migrate_state
from .ui import select_ui_mode, tui_available


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


def _add_workdir_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workdir",
        default=None,
        metavar="PATH",
        help=(
            "State directory. Defaults to .simpleworkflow beside the workflow YAML; "
            "an explicit relative path is resolved from the current directory."
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simpleworkflow",
        description="Lightweight YAML workflow runner for scientific pipelines.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("run", "plan", "status", "reset", "validate", "explain"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("workflow")
        _add_workdir_option(command_parser)
        command_parser.add_argument(
            "--debug", action="store_true", help="Show technical traceback details."
        )
        _add_cycle_options(command_parser)
        _add_display_options(command_parser)
        if command == "run":
            command_parser.add_argument("--force", action="store_true")
            command_parser.add_argument("--dry-run", action="store_true")
            command_parser.add_argument(
                "--ui",
                choices=("auto", "tui", "plain"),
                default="auto",
                help="Presentation mode: auto (default), tui or plain.",
            )
        if command in {"run", "plan", "validate", "explain"}:
            command_parser.add_argument(
                "--task",
                action="append",
                dest="selected_tasks",
                metavar="NAME",
                help="Select a task and include all of its dependencies; repeat as needed.",
            )

    monitor_parser = subparsers.add_parser(
        "monitor",
        help="Open the read-only interactive monitor for persisted workflow state.",
    )
    monitor_parser.add_argument("workflow")
    _add_workdir_option(monitor_parser)
    _add_display_options(monitor_parser)
    monitor_parser.add_argument(
        "--refresh-seconds",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="Monitor refresh interval in seconds (default: 1.0).",
    )
    monitor_parser.add_argument(
        "--debug", action="store_true", help="Show technical traceback details."
    )

    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Inspect or migrate a pre-0.4 state database.",
    )
    migrate_parser.add_argument("workflow")
    _add_workdir_option(migrate_parser)
    _add_display_options(migrate_parser)
    migrate_parser.add_argument(
        "--legacy-workflow",
        metavar="INSTANCE",
        help="Select one explicitly listed legacy instance when a shared DB is ambiguous.",
    )
    migrate_parser.add_argument(
        "--check",
        action="store_true",
        help="Inspect the state format and possible legacy instances without modifying files.",
    )
    migrate_parser.add_argument(
        "--debug", action="store_true", help="Show technical traceback details."
    )
    return parser


def _resolve_workdir(config: dict[str, Any], requested: str | None) -> Path:
    if requested is None:
        source_dir = Path(
            config.get("__simpleworkflow__", {}).get("source_dir", Path.cwd())
        )
        return (source_dir / ".simpleworkflow").resolve(strict=False)
    path = Path(requested).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve(strict=False)


def _cycle_engines(
    config: dict[str, Any],
    args: argparse.Namespace,
    reporter: WorkflowReporter,
) -> Iterable[tuple[CycleContext | None, WorkflowEngine]]:
    cycles = resolve_cycle_contexts(
        config.get("cycle"),
        cycle_times=getattr(args, "cycle_times", None),
        start=getattr(args, "cycle_start", None),
        end=getattr(args, "cycle_end", None),
        step=getattr(args, "cycle_step", None),
    )
    workdir = _resolve_workdir(config, args.workdir)
    selected = set(args.selected_tasks) if getattr(args, "selected_tasks", None) else None
    if not cycles:
        yield None, WorkflowEngine(
            config=config,
            workdir=workdir,
            force=getattr(args, "force", False),
            dry_run=getattr(args, "dry_run", False),
            reporter=reporter,
            selected_tasks=selected,
        )
        return

    for cycle in cycles:
        resolved = deepcopy(config)
        resolved["context"] = {
            **resolved.get("context", {}),
            **cycle.render_context(),
        }
        yield cycle, WorkflowEngine(
            config=resolved,
            workdir=workdir,
            force=getattr(args, "force", False),
            dry_run=getattr(args, "dry_run", False),
            reporter=reporter,
            selected_tasks=selected,
            cycle_id=cycle.cycle_id,
            cycle_time=cycle.cycle_time,
        )


def _heading(command: str, config: dict[str, Any], cycle: CycleContext | None) -> str:
    workflow_name = config.get("workflow", {}).get("name", "workflow")
    title = f"{command.title()} · {workflow_name}"
    return f"{title} · {cycle.cycle_time}" if cycle is not None else title


def _reconcile_after_interrupt(engine: WorkflowEngine) -> None:
    """Recover task state conservatively after an interactive interruption."""
    running_pbs = {
        task["name"]
        for task in engine.tasks
        if task.get("executor", "local") == "pbs"
        and engine.state.get_status(task["name"], cycle_id=engine.cycle_id) == "running"
    }
    engine.state.reconcile_running(cycle_id=engine.cycle_id)
    for task_name in running_pbs:
        state = engine.state.get_task_state(task_name, cycle_id=engine.cycle_id)
        if state is not None and state.status == "interrupted":
            engine.state.set_status(
                task_name,
                "unknown",
                None,
                state.signature,
                "submissão PBS interrompida antes de confirmar o job; verifique o escalonador",
                state.attempt_path,
                cycle_id=engine.cycle_id,
                signature_schema=state.signature_schema,
                signature_payload=state.signature_payload,
            )


def _inspection_lines(inspection: StateInspection) -> list[str]:
    if inspection.kind == "missing":
        return ["Nenhum state.sqlite3 encontrado."]
    if inspection.kind == "empty":
        return ["O state.sqlite3 existe, mas ainda não contém schema."]
    if inspection.kind == "versioned":
        return [f"State schema versionado: {inspection.schema_version}."]
    if inspection.kind == "legacy":
        lines = [f"Estado legado detectado: simpleWorkflow {inspection.legacy_version}."]
        if inspection.groups:
            lines.append("Instâncias lógicas encontradas:")
            lines.extend(f"  - {group.selector}" for group in inspection.groups)
        return lines
    return ["Formato de state.sqlite3 não reconhecido com segurança."]


def _run_migration(
    config: dict[str, Any],
    args: argparse.Namespace,
    reporter: TerminalReporter,
) -> int:
    workdir = _resolve_workdir(config, args.workdir)
    state_path = workdir / "state.sqlite3"
    reporter.heading(_heading("migrate", config, None))
    inspection = inspect_state(state_path)
    if args.check:
        for line in _inspection_lines(inspection):
            reporter.note(line)
        reporter.note(f"Estado: {state_path}")
        return 0 if inspection.kind not in {"unknown", "invalid"} else 2

    source_path = config.get("__simpleworkflow__", {}).get("source_path")
    if not source_path:
        raise MigrationError("migration requires a workflow loaded from a YAML file")
    result = migrate_state(
        state_path=state_path,
        workflow_name=config["workflow"]["name"],
        source_path=source_path,
        legacy_selector=args.legacy_workflow,
    )
    if not result.migrated:
        reporter.note("O banco já usa o schema atual; nenhuma alteração foi necessária.")
        return 0
    reporter.note(
        f"Migração concluída: {result.inspection.legacy_version} -> schema atual."
    )
    if result.selected_group:
        reporter.note(f"Instância migrada: {result.selected_group.selector}")
    if result.backup_path:
        reporter.note(f"Backup preservado em: {result.backup_path}")
    reporter.note("Use 'swf status <workflow.yaml>' para verificar o estado migrado.")
    return 0


def _tui_color_enabled(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return not bool(os.environ.get("NO_COLOR"))


def _launch_monitor(
    config: dict[str, Any],
    workflow_path: Path,
    workdir: Path,
    *,
    refresh_seconds: float,
    color: bool,
) -> None:
    """Import the optional Textual frontend only when it is explicitly needed."""
    if not tui_available():
        raise RuntimeError(
            'interactive monitor requires pip install "simpleworkflow[tui]"'
        )
    from .tui import run_monitor

    run_monitor(
        config,
        workflow_path,
        workdir,
        refresh_seconds=refresh_seconds,
        color=color,
    )


def _run_plain(
    config: dict[str, Any], args: argparse.Namespace, reporter: TerminalReporter
) -> int:
    for cycle, engine in _cycle_engines(config, args, reporter):
        try:
            reporter.heading(_heading("run", config, cycle))
            result = engine.run()
            if result != 0:
                return result
        except KeyboardInterrupt:
            _reconcile_after_interrupt(engine)
            raise
        finally:
            engine.state.close()
    return 0


def _main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_workflow(args.workflow)

    if args.command == "monitor":
        if args.refresh_seconds <= 0:
            raise ValueError("--refresh-seconds must be a positive number")
        workflow_path = Path(
            config.get("__simpleworkflow__", {}).get("source_path", args.workflow)
        ).resolve(strict=False)
        _launch_monitor(
            config,
            workflow_path,
            _resolve_workdir(config, args.workdir),
            refresh_seconds=float(args.refresh_seconds),
            color=_tui_color_enabled(args.color),
        )
        return 0

    reporter = TerminalReporter(color=args.color)

    if args.command == "migrate":
        return _run_migration(config, args, reporter)

    if args.command == "plan":
        index = 1
        for cycle, engine in _cycle_engines(config, args, reporter):
            try:
                reporter.heading(_heading("plan", config, cycle))
                for task_name in engine.plan():
                    reporter.plan_item(index, task_name)
                    index += 1
            finally:
                engine.state.close()
        return 0

    if args.command == "run":
        mode = select_ui_mode(
            args.ui,
            stdin=sys.stdin,
            stdout=sys.stdout,
            term=os.environ.get("TERM"),
            tui_available=tui_available(),
        )
        if mode == "tui":
            if args.dry_run:
                raise RuntimeError("--ui tui is not available with --dry-run; use --ui plain")
            raise RuntimeError(
                "interactive run integration is not enabled yet on this development branch; "
                "use --ui plain"
            )
        return _run_plain(config, args, reporter)

    if args.command == "status":
        for cycle, engine in _cycle_engines(config, args, reporter):
            try:
                reporter.heading(_heading("status", config, cycle))
                engine.status()
            finally:
                engine.state.close()
        return 0

    if args.command == "reset":
        for cycle, engine in _cycle_engines(config, args, reporter):
            try:
                reporter.heading(_heading("reset", config, cycle))
                engine.reset()
            finally:
                engine.state.close()
        reporter.note("Workflow state reset; run and attempt history was preserved.")
        return 0

    if args.command == "validate":
        failed = False
        for cycle, engine in _cycle_engines(config, args, reporter):
            try:
                reporter.heading(_heading("validate", config, cycle))
                problems = engine.validate()
                if problems:
                    failed = True
                    for problem in problems:
                        reporter.note(problem)
                else:
                    reporter.note("Workflow válido e pronto para execução.")
            finally:
                engine.state.close()
        return 2 if failed else 0

    if args.command == "explain":
        for cycle, engine in _cycle_engines(config, args, reporter):
            try:
                reporter.heading(_heading("explain", config, cycle))
                engine.explain()
            finally:
                engine.state.close()
        return 0

    return 2


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    debug = "--debug" in arguments
    try:
        return _main(arguments)
    except KeyboardInterrupt:
        if debug:
            traceback.print_exc()
        else:
            print(
                "simpleworkflow: execução interrompida pelo usuário; "
                "o estado foi preservado para recuperação segura.",
                file=sys.stderr,
            )
        return 130
    except (FileNotFoundError, ValueError, RuntimeError, MigrationError) as error:
        if debug:
            traceback.print_exc()
        else:
            print(f"simpleworkflow: {error}", file=sys.stderr)
            print("Use --debug to show technical details.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
