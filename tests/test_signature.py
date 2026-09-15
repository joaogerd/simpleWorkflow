from __future__ import annotations

import os
import shutil
from pathlib import Path

import simpleworkflow.signature as signature_module
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
    stat_result = source.stat()
    before = fingerprint_artifact(source, "sha256")

    source.write_text("bbbb", encoding="utf-8")
    os.utime(source, ns=(stat_result.st_atime_ns, stat_result.st_mtime_ns))
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


def test_directory_fingerprint_includes_children(tmp_path: Path) -> None:
    directory = tmp_path / "inputs"
    directory.mkdir()
    child = directory / "field.nc"
    child.write_text("first", encoding="utf-8")
    before = fingerprint_artifact(directory, "sha256")
    child.write_text("second", encoding="utf-8")
    after = fingerprint_artifact(directory, "sha256")
    assert before["children"][0]["sha256"] != after["children"][0]["sha256"]


def test_runtime_identity_uses_task_path_override(tmp_path: Path, monkeypatch: object) -> None:
    tool = tmp_path / "science-tool"
    tool.write_text("tool", encoding="utf-8")
    seen_paths: list[str | None] = []

    def fake_which(command: str, path: str | None = None) -> str:
        assert command == "science-tool"
        seen_paths.append(path)
        return str(tool)

    monkeypatch.setattr(signature_module.shutil, "which", fake_which)  # type: ignore[attr-defined]
    task_path = str(tmp_path / "task-bin")
    result = compute_task_signature(
        workflow_path=tmp_path / "workflow.yaml",
        task_name="analysis",
        argv=["science-tool"],
        cwd=tmp_path,
        env={"PATH": task_path},
        artifacts=ResolvedArtifacts(),
    )

    assert seen_paths == [task_path]
    assert result.payload["task"]["runtime"]["resolved"] == "$WORKFLOW/science-tool"


def test_runtime_identity_resolves_relative_executable_from_task_cwd(tmp_path: Path) -> None:
    execution_dir = tmp_path / "case"
    tool = execution_dir / "bin" / "science-tool"
    tool.parent.mkdir(parents=True)
    tool.write_text("tool", encoding="utf-8")

    result = compute_task_signature(
        workflow_path=tmp_path / "workflow.yaml",
        task_name="analysis",
        argv=["./bin/science-tool"],
        cwd=execution_dir,
        env={},
        artifacts=ResolvedArtifacts(),
    )

    assert result.payload["task"]["runtime"]["resolved"] == "$WORKFLOW/case/bin/science-tool"


def test_signature_changes_when_resolved_executable_metadata_changes(
    tmp_path: Path, monkeypatch: object
) -> None:
    tool = tmp_path / "science-tool"
    tool.write_text("first", encoding="utf-8")
    monkeypatch.setattr(  # type: ignore[attr-defined]
        signature_module.shutil,
        "which",
        lambda _command, path=None: str(tool),
    )
    common = {
        "workflow_path": tmp_path / "workflow.yaml",
        "task_name": "analysis",
        "argv": ["science-tool"],
        "cwd": tmp_path,
        "env": {"PATH": str(tmp_path)},
        "artifacts": ResolvedArtifacts(),
    }

    before = compute_task_signature(**common)
    tool.write_text("changed executable contents", encoding="utf-8")
    after = compute_task_signature(**common)

    assert before.value != after.value


def test_signature_survives_move_of_complete_workflow_root(tmp_path: Path) -> None:
    first_root = tmp_path / "case-a"
    first_root.mkdir()
    workflow = first_root / "workflow.yaml"
    source = first_root / "background.nc"
    workflow.write_text("workflow: {name: portable}\n", encoding="utf-8")
    source.write_text("background", encoding="utf-8")
    before = signature_for(workflow, source)

    second_root = tmp_path / "case-b"
    shutil.move(str(first_root), second_root)
    after = signature_for(second_root / "workflow.yaml", second_root / "background.nc")

    assert before.value == after.value
    assert before.payload == after.payload
    assert "simpleworkflow_version" not in after.payload
    assert "workflow_source" not in after.payload
    assert after.payload["task"]["inputs"]["required"][0]["path"] == "$WORKFLOW/background.nc"
