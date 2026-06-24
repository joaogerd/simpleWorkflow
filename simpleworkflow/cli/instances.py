from __future__ import annotations

import argparse
from pathlib import Path

from ..cycles import CyclePoint, resolve_cycle_points
from ..engine import WorkflowEngine


def build_engines(config: dict, args: argparse.Namespace):
    points = resolve_cycle_points(
        config.get("cycle"),
        start_override=args.cycle_start,
        end_override=args.cycle_end,
        step_override=args.cycle_step,
        cycle_time=args.cycle_time,
    )
    if not points:
        return [(None, WorkflowEngine(
            config=config,
            workdir=args.workdir,
            force=getattr(args, "force", False),
            dry_run=getattr(args, "dry_run", False),
        ))]

    result = []
    for point in points:
        cycle_config = dict(config)
        context = dict(config.get("context", {}))
        context.update(cycle_time=point.time, cycle_id=point.identifier)
        cycle_config["context"] = context
        result.append((point, WorkflowEngine(
            config=cycle_config,
            workdir=Path(args.workdir) / "cycles" / point.identifier,
            force=getattr(args, "force", False),
            dry_run=getattr(args, "dry_run", False),
        )))
    return result
