"""Portable end-to-end test of the synthetic scientific example."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from simpleworkflow.cli import main


def test_synthetic_series_workflow_runs_and_reuses(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "examples" / "reproducible-study"
    example = tmp_path / "reproducible-study"
    shutil.copytree(
        source,
        example,
        ignore=shutil.ignore_patterns(".simpleworkflow", "data"),
    )
    workflow = example / "workflow.yaml"

    assert main(["plan", str(workflow), "--color", "never"]) == 0
    assert main(["validate", str(workflow), "--color", "never"]) == 0
    assert main(["run", str(workflow), "--ui", "plain", "--color", "never"]) == 0

    with (example / "data" / "monthly_temperature.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        temperature = list(csv.DictReader(stream))
    with (example / "data" / "monthly_anomalies.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        anomalies = list(csv.DictReader(stream))

    summary_path = example / "data" / "trend_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert len(temperature) == len(anomalies) == 60
    assert summary["n_months"] == 60
    assert summary["data_type"] == "synthetic_monthly_temperature_anomalies"
    assert 0 < summary["trend_degrees_c_per_year"] < 1
    assert summary["residual_rms_degrees_c"] >= 0

    before = summary_path.read_bytes()
    assert main(["run", str(workflow), "--ui", "plain", "--color", "never"]) == 0
    assert summary_path.read_bytes() == before

    # A changed scientific implementation must invalidate reuse, even when the
    # executable (Python) and the existing data products are unchanged.
    script_path = example / "pipeline.py"
    script = script_path.read_text(encoding="utf-8")
    assert "0.015 * index" in script
    script_path.write_text(
        script.replace("0.015 * index", "0.025 * index"),
        encoding="utf-8",
    )
    assert main(["run", str(workflow), "--ui", "plain", "--color", "never"]) == 0
    assert summary_path.read_bytes() != before
    assert main(["status", str(workflow), "--color", "never"]) == 0
