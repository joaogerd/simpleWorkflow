from __future__ import annotations

import json
from pathlib import Path

from simpleworkflow.monitor import AttemptSnapshot, TaskSnapshot
from simpleworkflow.tui_resources import (
    InspectableResource,
    discover_attempt_resources,
    discover_related_files,
    is_probably_text,
)


def _attempt(
    directory: Path,
    *,
    metadata: dict[str, object] | None = None,
    scheduler: dict[str, object] | None = None,
) -> AttemptSnapshot:
    directory.mkdir(parents=True, exist_ok=True)
    if metadata is not None:
        (directory / "metadata.json").write_text(
            json.dumps(metadata) + "\n",
            encoding="utf-8",
        )
    if scheduler is not None:
        (directory / "scheduler.json").write_text(
            json.dumps(scheduler) + "\n",
            encoding="utf-8",
        )
    return AttemptSnapshot(
        run_id="run-1",
        task_name="analysis",
        cycle_id="2018041506",
        attempt=1,
        status="running",
        return_code=None,
        reason=None,
        directory=directory,
        started_at="2018-04-15T06:01:04Z",
        finished_at=None,
    )


def _task(attempt: AttemptSnapshot) -> TaskSnapshot:
    return TaskSnapshot(
        name="analysis",
        status="running",
        cycle_id="2018041506",
        attempts=(attempt,),
    )


def test_discover_attempt_resources_prefers_structured_provenance(tmp_path: Path) -> None:
    attempt_dir = tmp_path / "attempt-001"
    attempt_dir.mkdir()
    stdout = attempt_dir / "stdout.log"
    stderr = attempt_dir / "stderr.log"
    pbs_out = attempt_dir / "pbs.stdout.log"
    pbs_err = attempt_dir / "pbs.stderr.log"
    job = attempt_dir / "job.pbs"
    started = attempt_dir / "started.json"
    for path in (stdout, stderr, pbs_out, pbs_err, job, started):
        path.write_text("x\n", encoding="utf-8")

    attempt = _attempt(
        attempt_dir,
        metadata={
            "execution": {
                "executor": "pbs",
                "job_id": "363911.pbs-ha",
                "job_stdout": str(pbs_out),
                "job_stderr": str(pbs_err),
                "script": str(job),
            }
        },
    )
    resources = discover_attempt_resources(_task(attempt), attempt, {})

    assert [resource.key for resource in resources[:4]] == [
        "stdout",
        "stderr",
        "pbs_stdout",
        "pbs_stderr",
    ]
    assert any(resource.path == job and resource.kind == "pbs-script" for resource in resources)
    assert any(resource.path == attempt_dir / "metadata.json" for resource in resources)
    assert all(resource.origin == "structured" for resource in resources)


def test_local_attempt_does_not_invent_pbs_resources(tmp_path: Path) -> None:
    attempt_dir = tmp_path / "attempt-001"
    attempt_dir.mkdir()
    (attempt_dir / "stdout.log").write_text("ok\n", encoding="utf-8")
    (attempt_dir / "stderr.log").write_text("", encoding="utf-8")
    attempt = _attempt(
        attempt_dir,
        metadata={"execution": {"executor": "local"}},
    )

    resources = discover_attempt_resources(_task(attempt), attempt, {})
    keys = {resource.key for resource in resources}

    assert "stdout" in keys
    assert "stderr" in keys
    assert "pbs_stdout" not in keys
    assert "pbs_stderr" not in keys
    assert "pbs_script" not in keys
    assert "scheduler" not in keys


def test_resources_include_persisted_declared_artifacts_without_duplicates(
    tmp_path: Path,
) -> None:
    attempt_dir = tmp_path / "attempt-001"
    attempt_dir.mkdir()
    output = tmp_path / "analysis.nc"
    output.write_text("text fixture\n", encoding="utf-8")
    attempt = _attempt(
        attempt_dir,
        metadata={
            "execution": {"executor": "local"},
            "artifacts": {
                "inputs": {"required": [], "optional": []},
                "outputs": {
                    "required": [str(output)],
                    "checks": [
                        {
                            "path": str(output),
                            "kind": "file",
                            "nonempty": True,
                        }
                    ],
                },
            },
        },
    )

    resources = discover_attempt_resources(_task(attempt), attempt, {})
    paths = [resource.path for resource in resources]

    assert paths.count(output.resolve(strict=False)) == 1
    output_resource = next(resource for resource in resources if resource.path == output)
    assert output_resource.kind == "output"
    assert output_resource.origin == "structured"


def test_related_file_discovery_links_only_existing_regular_files(tmp_path: Path) -> None:
    cwd = tmp_path / "case"
    cwd.mkdir()
    manifest = cwd / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    missing = cwd / "missing.json"
    text = (
        f"[OK] validation manifest accepted: {manifest}\n"
        f"missing: {missing}\n"
        "not-a-path: /definitely/not/a/real/file\n"
    )

    resources = discover_related_files(
        text,
        cwd=cwd,
        attempt_dir=tmp_path,
    )

    assert [resource.path for resource in resources] == [manifest]
    assert resources[0].origin == "log"
    assert resources[0].kind == "json"


def test_related_file_discovery_resolves_dot_relative_paths_only_from_known_context(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "case"
    cwd.mkdir()
    manifest = cwd / "manifest.yaml"
    manifest.write_text("accepted: true\n", encoding="utf-8")

    resources = discover_related_files(
        "accepted: ./manifest.yaml\nignored: manifest.yaml\n",
        cwd=cwd,
        attempt_dir=tmp_path / "attempt",
    )

    assert [resource.path for resource in resources] == [manifest]


def test_related_file_discovery_deduplicates_known_structured_paths(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    known = InspectableResource(
        key="output:0",
        label="manifest.json",
        path=manifest,
        kind="output",
        origin="structured",
    )

    resources = discover_related_files(
        f"accepted: {manifest}\n",
        cwd=tmp_path,
        attempt_dir=tmp_path,
        known_paths=(known.path,),
    )

    assert resources == ()


def test_is_probably_text_rejects_binary_and_accepts_utf8(tmp_path: Path) -> None:
    text = tmp_path / "text.log"
    text.write_text("hello μ-world\n", encoding="utf-8")
    binary = tmp_path / "field.nc"
    binary.write_bytes(b"CDF\x00\x01\x02")

    assert is_probably_text(text)
    assert not is_probably_text(binary)
    assert not is_probably_text(tmp_path / "missing.txt")
