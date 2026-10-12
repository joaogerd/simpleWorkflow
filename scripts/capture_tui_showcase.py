from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "examples" / "tui-showcase"
OUTPUT = ROOT / "docs" / "tutorial" / "tui-showcase"

CASES = [
    ("01-minimal", "Minimal", "The smallest useful TUI: one workflow, one task and the core views.", ("monitor",)),
    ("02-workflow", "Standard workflow", "Dependencies, multiple tasks, stdout/stderr and a skipped optional task.", ("monitor", "logs")),
    ("03-artifacts", "Artifacts and contracts", "Inputs, outputs, checks, environment, cwd and reusable state.", ("monitor", "logs")),
    ("04-campaign", "Generic campaign", "Initialization plus four generic cycles, cycle navigation and campaign overview.", ("monitor", "cycles", "campaign", "logs")),
    ("05-problems", "Failure diagnosis", "A deliberate process failure with Problems and log evidence.", ("monitor", "problems", "logs")),
    ("06-invalid-input", "Invalid input", "A required input is missing before the process can start.", ("monitor", "problems")),
    ("07-invalid-output", "Invalid output", "The process exits successfully but violates its output contract.", ("monitor", "problems")),
    ("08-blocked", "Blocked dependency", "A disabled prerequisite leaves its downstream task blocked.", ("monitor", "problems")),
    ("09-timeout", "Timeout", "A local task exceeds its time limit and records diagnostic evidence.", ("monitor", "problems", "logs")),
]

EXPECTED_FAILURES = {
    "05-problems",
    "06-invalid-input",
    "07-invalid-output",
    "08-blocked",
    "09-timeout",
}

GENERATED_DIRS = {
    "03-artifacts": ("demo-work",),
    "04-campaign": ("campaign-work",),
    "05-problems": ("problem-work",),
    "07-invalid-output": ("invalid-output-work",),
}


def _swf(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "simpleworkflow.cli", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _prepare(case: str, workflow: Path) -> None:
    shutil.rmtree(workflow.parent / ".simpleworkflow", ignore_errors=True)
    for dirname in GENERATED_DIRS.get(case, ()):
        shutil.rmtree(workflow.parent / dirname, ignore_errors=True)
    result = _swf("run", str(workflow), "--ui", "plain", "--color", "never")
    if result.returncode != 0 and case not in EXPECTED_FAILURES:
        raise RuntimeError(
            f"showcase {case} failed unexpectedly with {result.returncode}:\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )


def _capture(case: str, workflow: Path, view: str) -> Path:
    output = OUTPUT / f"{case}-{view}.svg"
    result = _swf(
        "capture-tui",
        str(workflow),
        "--view",
        view,
        "--size",
        "140x45",
        "--output",
        str(output),
        "--color",
        "always",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"capture failed for {case}/{view}:\n{result.stderr}"
        )
    return output


def _write_gallery(images: list[tuple[str, str, Path]]) -> None:
    lines = [
        "# simpleWorkflow TUI showcase",
        "",
        "Generated from deterministic 140x45 virtual terminal captures.",
        "",
    ]
    current = None
    for case, view, image in images:
        if case != current:
            current = case
            lines.extend([f"## {case}", ""])
        relative = image.relative_to(OUTPUT.parent)
        lines.extend(
            [
                f"### {view}",
                "",
                f"![{case} - {view}]({relative.as_posix()})",
                "",
            ]
        )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    (OUTPUT.parent / "tui-showcase.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )




def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    images: list[tuple[str, str, Path]] = []
    for case, _title, _description, views in CASES:
        workflow = SHOWCASE / case / "workflow.yaml"
        _prepare(case, workflow)
        for view in views:
            images.append((case, view, _capture(case, workflow, view)))
    _write_gallery(images)
    print(OUTPUT.parent / "showcase.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
