"""Deterministic, synthetic climate-series workflow for portable verification.

This example is a software demonstration, not an empirical climate study.
Only Python's standard library is required.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def prepare_output(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def generate(output: Path) -> None:
    """Build five years of monthly synthetic observations, with no random seed."""
    prepare_output(output)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["month", "month_index", "temperature_c"])
        for index in range(60):
            year = 2020 + index // 12
            month = 1 + index % 12
            # Seasonal cycle, linear trend and deterministic interannual variability.
            temperature = (
                15.0
                + 7.0 * math.sin(2.0 * math.pi * (month - 1) / 12.0)
                + 0.015 * index
                + 0.25 * math.cos(2.0 * math.pi * index / 5.0)
            )
            writer.writerow([f"{year:04d}-{month:02d}", month, f"{temperature:.8f}"])


def anomalies(source: Path, output: Path) -> None:
    """Subtract the empirical mean for each calendar month of the generated series."""
    rows = read_rows(source)
    if not rows:
        raise ValueError("Input series is empty.")
    grouped: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        grouped[int(row["month_index"])].append(float(row["temperature_c"]))
    climate_mean = {
        month: sum(values) / len(values) for month, values in grouped.items()
    }
    prepare_output(output)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["month", "temperature_anomaly_c"])
        for row in rows:
            anomaly = float(row["temperature_c"]) - climate_mean[int(row["month_index"])]
            writer.writerow([row["month"], f"{anomaly:.8f}"])


def summary(source: Path, output: Path) -> None:
    """Estimate a least-squares linear trend from the synthetic anomaly series."""
    rows = read_rows(source)
    if len(rows) < 2:
        raise ValueError("At least two monthly anomalies are required.")
    values = [float(row["temperature_anomaly_c"]) for row in rows]
    count = len(values)
    x_mean = (count - 1) / 2.0
    y_mean = sum(values) / count
    numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(count))
    slope_monthly = numerator / denominator
    residual_variance = sum(
        (y - (y_mean + slope_monthly * (i - x_mean))) ** 2
        for i, y in enumerate(values)
    ) / count
    record = {
        "data_type": "synthetic_monthly_temperature_anomalies",
        "n_months": count,
        "trend_degrees_c_per_year": round(12.0 * slope_monthly, 8),
        "residual_rms_degrees_c": round(math.sqrt(residual_variance), 8),
    }
    prepare_output(output)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=["generate", "anomalies", "summary"])
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.step == "generate":
        generate(args.output)
        return
    if args.input is None:
        parser.error("--input is required for anomalies and summary")
    if args.step == "anomalies":
        anomalies(args.input, args.output)
    else:
        summary(args.input, args.output)


if __name__ == "__main__":
    main()
