from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simpleworkflow",
        description="Lightweight YAML workflow runner for scientific pipelines.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "plan", "status", "reset"):
        item = subparsers.add_parser(command)
        item.add_argument("workflow")
        item.add_argument("--workdir", default=".simpleworkflow")
        item.add_argument("--from", dest="cycle_start", metavar="TIME")
        item.add_argument("--to", dest="cycle_end", metavar="TIME")
        item.add_argument("--step", dest="cycle_step", metavar="DURATION")
        item.add_argument("--cycle-time", metavar="TIME")
        if command == "run":
            item.add_argument("--force", action="store_true")
            item.add_argument("--dry-run", action="store_true")
    return parser
