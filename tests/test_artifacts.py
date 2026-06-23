from __future__ import annotations

from pathlib import Path

from simpleworkflow.artifacts import resolve_task_artifacts


def test_resolves_rendered_paths_and_expands_optional_globs(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    obs_dir = case_dir / "obs"
    obs_dir.mkdir(parents=True)
    background = case_dir / "background.nc"
    background.write_text("background", encoding="utf-8")
    sondes = obs_dir / "sondes.nc4"
    sondes.write_text("sondes", encoding="utf-8")
    surface = obs_dir / "surface.nc4"
    surface.write_text("surface", encoding="utf-8")

    task = {
        "inputs": {
            "required": ["{case_dir}/background.nc", "wrappers/run.sh"],
            "optional": ["{case_dir}/obs/*.nc4", "{case_dir}/missing/*.nc4"],
        },
        "outputs": {"required": ["{case_dir}/analysis.nc"]},
    }
    artifacts = resolve_task_artifacts(
        task,
        {"case_dir": str(case_dir)},
        tmp_path,
    )

    assert artifacts.required_inputs == (
        background.resolve(),
        (tmp_path / "wrappers" / "run.sh").resolve(),
    )
    assert artifacts.optional_inputs == (sondes.resolve(), surface.resolve())
    assert artifacts.required_outputs == ((case_dir / "analysis.nc").resolve(),)
    assert artifacts.missing_required_inputs() == (
        (tmp_path / "wrappers" / "run.sh").resolve(),
    )
