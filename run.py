#!/usr/bin/env python
"""Compatibility entry point for simpleWorkflow.

Prefer using the installed CLI directly:

    simpleworkflow run examples/hello.yaml

This wrapper is kept so existing habits like `python run.py run workflow.yaml`
continue to work without storing configuration or credentials in the source tree.
"""

from simpleworkflow.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
