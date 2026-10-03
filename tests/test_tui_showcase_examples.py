from __future__ import annotations

import shutil
from pathlib import Path

from simpleworkflow.cli import main


REPO_ROOT = Path(__file__).resolve().parents[1]
SHOWCASE_ROOT = REPO_ROOT / "examples" / "tui-showcase"


def _copy_case(tmp_path: Path, name: str) -> Path:
    target = tmp_path / name
    shutil.copytree(SHOWCASE_ROOT / name, target)
    return target / "workflow.yaml"


def test_artifacts_showcase_runs_end_to_end(tmp_path: Path) -> None:
    workflow = _copy_case(tmp_path, "03-artifacts")

    assert main(["run", str(workflow), "--ui", "plain", "--color", "never"]) == 0
    assert (workflow.parent / "demo-work" / "input.txt").is_file()
    assert (workflow.parent / "demo-work" / "output.txt").is_file()


def test_campaign_showcase_runs_all_cycles_end_to_end(tmp_path: Path) -> None:
    workflow = _copy_case(tmp_path, "04-campaign")

    assert main(["run", str(workflow), "--ui", "plain", "--color", "never"]) == 0

    work = workflow.parent / "campaign-work"
    assert (work / "initialized.txt").is_file()
    assert sorted(path.name for path in work.glob("input_*.txt")) == [
        "input_2026100300.txt",
        "input_2026100306.txt",
        "input_2026100312.txt",
        "input_2026100318.txt",
    ]
    assert sorted(path.name for path in work.glob("result_*.txt")) == [
        "result_2026100300.txt",
        "result_2026100306.txt",
        "result_2026100312.txt",
        "result_2026100318.txt",
    ]
