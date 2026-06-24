from __future__ import annotations

from ..config import load_workflow
from .arguments import build_parser
from .instances import build_engines


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    engines = build_engines(load_workflow(args.workflow), args)

    for point, engine in engines:
        if args.command == "plan":
            prefix = f"{point.identifier}/" if point else ""
            for index, task in enumerate(engine.plan(), 1):
                print(f"{prefix}{index:02d}. {task}")
        elif args.command == "run":
            if point:
                print(f"[CYCLE] {point.time}")
            result = engine.run()
            if result:
                return result
        elif args.command == "status":
            if point:
                print(f"[CYCLE] {point.time}")
            engine.status()
        else:
            engine.reset()
            print(f"Cycle {point.time} state reset." if point else "Workflow state reset.")
    return 0
