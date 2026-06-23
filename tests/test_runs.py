from __future__ import annotations

import json

import pytest

from simpleworkflow.runs import RunRecorder


def test_recorder_creates_immutable_attempt_directories(tmp_path) -> None:
    recorder = RunRecorder(tmp_path, "demo workflow", run_id="run-001")

    first = recorder.begin_attempt("run/analysis")
    second = recorder.begin_attempt("run/analysis")

    assert first.run_id == "run-001"
    assert first.attempt == 1
    assert second.attempt == 2
    assert first.directory != second.directory
    assert first.stdout_path.is_file()
    assert first.stderr_path.is_file()
    assert second.stdout_path.is_file()
    assert second.stderr_path.is_file()

    manifest = json.loads((tmp_path / "runs" / "run-001" / "run.json").read_text())
    assert manifest["workflow"] == "demo workflow"


def test_attempt_metadata_is_written_once(tmp_path) -> None:
    recorder = RunRecorder(tmp_path, "demo", run_id="run-001")
    attempt = recorder.begin_attempt("analysis")

    recorder.write_metadata(
        attempt,
        {
            "status": "success",
            "return_code": 0,
            "argv": ["python", "-c", "print('ok')"],
        },
    )
    metadata = json.loads(attempt.metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "success"
    assert metadata["logs"] == {"stdout": "stdout.log", "stderr": "stderr.log"}

    with pytest.raises(FileExistsError):
        recorder.write_metadata(attempt, {"status": "failed"})


def test_existing_run_id_cannot_be_reused(tmp_path) -> None:
    RunRecorder(tmp_path, "demo", run_id="run-001")

    with pytest.raises(FileExistsError):
        RunRecorder(tmp_path, "demo", run_id="run-001")
