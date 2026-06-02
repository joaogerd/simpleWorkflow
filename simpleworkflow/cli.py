from __future__ import annotations

import argparse

from .config import load_workflow
from .engine import WorkflowEngine


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

        if command == "run":
            command_parser.add_argument("--force", action="store_true")
            command_parser.add_argument("--dry-run", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_workflow(args.workflow)

    engine = WorkflowEngine(
        config=config,
        workdir=args.workdir,
        force=getattr(args, "force", False),
        dry_run=getattr(args, "dry_run", False),
    )

    if args.command == "plan":
        for index, task_name in enumerate(engine.plan(), start=1):
            print(f"{index:02d}. {task_name}")
        return 0

    if args.command == "run":
        return engine.run()

    if args.command == "status":
        engine.status()
        return 0

    if args.command == "reset":
        engine.reset()
        print("Workflow state reset.")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
