from __future__ import annotations

from simpleworkflow.artifacts import ResolvedArtifacts
from simpleworkflow.provenance import build_attempt_metadata
from simpleworkflow.signature import TaskSignature


def test_attempt_metadata_records_declared_execution_context_only(tmp_path) -> None:
    source = tmp_path / "background.nc"
    optional = tmp_path / "obs.nc4"
    output = tmp_path / "analysis.nc"
    signature = TaskSignature(
        value="abc123",
        payload={"task": {"name": "analysis"}, "workflow_sha256": "workflow"},
    )

    metadata = build_attempt_metadata(
        argv=["python", "-c", "print('analysis')"],
        cwd=tmp_path,
        env={"OMP_NUM_THREADS": "1", "FI_CXI_RX_MATCH_MODE": "hybrid"},
        artifacts=ResolvedArtifacts(
            required_inputs=(source,),
            optional_inputs=(optional,),
            required_outputs=(output,),
        ),
        signature=signature,
        status="success",
        return_code=0,
    )

    assert metadata["status"] == "success"
    assert metadata["command"] == {
        "argv": ["python", "-c", "print('analysis')"],
        "cwd": str(tmp_path.resolve()),
        "env": {
            "FI_CXI_RX_MATCH_MODE": "hybrid",
            "OMP_NUM_THREADS": "1",
        },
    }
    assert metadata["signature"] == {"value": "abc123", "payload": signature.payload}
    assert metadata["artifacts"]["inputs"]["required"] == [str(source.resolve())]
    assert metadata["artifacts"]["inputs"]["optional"] == [str(optional.resolve())]
    assert metadata["artifacts"]["outputs"]["required"] == [str(output.resolve())]
    assert "PATH" not in metadata["command"]["env"]


def test_attempt_metadata_records_framework_failure_separately(tmp_path) -> None:
    metadata = build_attempt_metadata(
        argv=["bash", "run.sh"],
        cwd=None,
        env={},
        artifacts=ResolvedArtifacts(),
        signature=TaskSignature(value="signature", payload={}),
        status="invalid-output",
        return_code=3,
        process_return_code=0,
        reason="missing required output",
    )

    assert metadata["return_code"] == 3
    assert metadata["process_return_code"] == 0
    assert metadata["reason"] == "missing required output"
