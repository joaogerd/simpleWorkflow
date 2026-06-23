from __future__ import annotations

import os
from pathlib import Path

from simpleworkflow.artifacts import ResolvedArtifacts
from simpleworkflow.signature import compute_task_signature, fingerprint_artifact


def signature_for(
    workflow: Path,
    input_path: Path,
    *,
    mode: str = "metadata",
    env: dict[str, str] | None = None,
    optional: tuple[Path, ...] = (),
):
    return compute_task_signature(
        workflow_path=workflow,
        task_name="analysis",
        argv=["python", "-c", "print('analysis')"],
        cwd=workflow.parent,
        env=env or {"OMP_NUM_THREADS": "1"},
        artifacts=ResolvedArtifacts(
            required_inputs=(input_path,),
            optional_inputs=optional,
            required_outputs=(workflow.parent / "analysis.nc",),
        ),
        fingerprint_mode=mode,
    )


def test_metadata_signature_changes_when_input_metadata_changes(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("tasks: []\n", encoding="utf-8")
    source = tmp_path / "background.nc"
    source.write_text("first", encoding="utf-8")

    before = signature_for(workflow, source)
    source.write_text("second-value", encoding="utf-8")
    after = signature_for(workflow, source)

    assert before.value != after.value
    assert after.payload["task"]["inputs"]["required"][0]["size"] == len("second-value")


def test_sha256_fingerprint_detects_changed_contents_with_preserved_metadata(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.nc"
    source.write_text("aaaa", encoding="utf-8")
    stat = source.stat()
    before = fingerprint_artifact(source, "sha256")

    source.write_text("bbbb", encoding="utf-8")
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    after = fingerprint_artifact(source, "sha256")

    assert before["size"] == after["size"]
    assert before["mtime_ns"] == after["mtime_ns"]
    assert before["sha256"] != after["sha256"]


def test_signature_is_deterministic_when_environment_mapping_order_changes(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("tasks: []\n", encoding="utf-8")
    source = tmp_path / "background.nc"
    source.write_text("background", encoding="utf-8")

    first = signature_for(workflow, source, env={"B": "2", "A": "1"})
    second = signature_for(workflow, source, env={"A": "1", "B": "2"})

    assert first.value == second.value
    assert first.payload == second.payload


def test_signature_changes_when_optional_input_set_changes(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text("tasks: []\n", encoding="utf-8")
    source = tmp_path / "background.nc"
    source.write_text("background", encoding="utf-8")
    optional = tmp_path / "obs.nc4"

    without_optional = signature_for(workflow, source)
    optional.write_text("observation", encoding="utf-8")
    with_optional = signature_for(workflow, source, optional=(optional,))

    assert without_optional.value != with_optional.value
