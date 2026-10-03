from __future__ import annotations

import json
import os

import pytest

from simpleworkflow.runs import RunRecorder, metadata_checksum_matches, write_durable_json


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
    assert (attempt.directory / "metadata.sha256").is_file()

    with pytest.raises(FileExistsError):
        recorder.write_metadata(attempt, {"status": "failed"})


def test_existing_run_id_cannot_be_reused(tmp_path) -> None:
    RunRecorder(tmp_path, "demo", run_id="run-001")

    with pytest.raises(FileExistsError):
        RunRecorder(tmp_path, "demo", run_id="run-001")



def test_durable_json_replace_fsyncs_file_and_directory(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fsync_calls: list[int] = []
    monkeypatch.setattr("simpleworkflow.runs.os.fsync", lambda descriptor: fsync_calls.append(descriptor))
    path = tmp_path / "runtime.json"

    write_durable_json(path, {"state": "first"})
    write_durable_json(path, {"state": "second"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"state": "second"}
    assert len(fsync_calls) == 4
    assert not list(tmp_path.glob(".runtime.json.*.tmp"))


def test_metadata_checksum_validation_supports_legacy_and_detects_tampering(tmp_path) -> None:
    metadata = tmp_path / "metadata.json"
    metadata.write_text('{"status":"success"}\n', encoding="utf-8")

    assert metadata_checksum_matches(metadata) is None

    import hashlib

    digest = hashlib.sha256(metadata.read_bytes()).hexdigest()
    (tmp_path / "metadata.sha256").write_text(digest + "\n", encoding="utf-8")
    assert metadata_checksum_matches(metadata) is True

    metadata.write_text('{"status":"failed"}\n', encoding="utf-8")
    assert metadata_checksum_matches(metadata) is False



def test_durable_json_replace_failure_preserves_previous_record(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "runtime.json"
    write_durable_json(path, {"state": "old"})

    def fail_replace(_source, _target) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("simpleworkflow.runs.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        write_durable_json(path, {"state": "new"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"state": "old"}
    assert not list(tmp_path.glob(".runtime.json.*.tmp"))


def test_durable_json_directory_fsync_failure_never_leaves_partial_json(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "runtime.json"
    original_fsync = os.fsync
    calls = 0

    def fail_directory_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("directory fsync failed")
        original_fsync(descriptor)

    monkeypatch.setattr("simpleworkflow.runs.os.fsync", fail_directory_fsync)
    with pytest.raises(OSError, match="directory fsync failed"):
        write_durable_json(path, {"state": "complete"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"state": "complete"}
    assert not list(tmp_path.glob(".runtime.json.*.tmp"))
