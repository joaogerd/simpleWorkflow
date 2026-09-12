from __future__ import annotations

import sys
from pathlib import Path

from simpleworkflow.engine import WorkflowEngine


def _append_and_copy_script(label: str, source: Path, target: Path, calls: Path) -> str:
    return (
        "from pathlib import Path; "
        f"source=Path({str(source)!r}); "
        f"target=Path({str(target)!r}); "
        f"calls=Path({str(calls)!r}); "
        f"calls.open('a', encoding='utf-8').write({(label + chr(10))!r}); "
        "target.write_text(source.read_text(encoding='utf-8'), encoding='utf-8')"
    )


def test_dependency_rerun_propagates_to_successful_downstream_task(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    prepared = tmp_path / "prepared.txt"
    result = tmp_path / "result.txt"
    calls = tmp_path / "calls.log"
    source.write_text("first", encoding="utf-8")

    config = {
        "workflow": {"name": "dependency-rerun"},
        "tasks": [
            {
                "name": "prepare",
                "argv": [
                    sys.executable,
                    "-c",
                    _append_and_copy_script("prepare", source, prepared, calls),
                ],
                "inputs": {"required": [str(source)]},
                "outputs": {"required": [str(prepared)]},
            },
            {
                "name": "consume",
                "depends_on": ["prepare"],
                "argv": [
                    sys.executable,
                    "-c",
                    _append_and_copy_script("consume", prepared, result, calls),
                ],
                # Deliberately do not declare prepared as a task input. The dependency
                # itself must guarantee rerun propagation when prepare executes again.
                "outputs": {"required": [str(result)]},
            },
        ],
        "__simpleworkflow__": {"source_dir": str(tmp_path)},
    }

    engine = WorkflowEngine(config=config, workdir=tmp_path / ".simpleworkflow")

    assert engine.run() == 0
    assert result.read_text(encoding="utf-8") == "first"
    assert calls.read_text(encoding="utf-8").splitlines() == ["prepare", "consume"]

    # Nothing changed: both successful tasks should be reused.
    assert engine.run() == 0
    assert calls.read_text(encoding="utf-8").splitlines() == ["prepare", "consume"]

    # Only prepare's own input changes. consume's signature and old output still
    # look reusable, but it must run again because its dependency actually reran.
    source.write_text("second-value", encoding="utf-8")
    assert engine.run() == 0
    assert result.read_text(encoding="utf-8") == "second-value"
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "prepare",
        "consume",
        "prepare",
        "consume",
    ]

    # Stable again: reuse both tasks after the propagated rerun completed.
    assert engine.run() == 0
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "prepare",
        "consume",
        "prepare",
        "consume",
    ]
