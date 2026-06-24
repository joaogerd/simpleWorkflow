from __future__ import annotations

from simpleworkflow.cycles import CycleConfigurationError, resolve_cycle_points


def test_documented_cycle_generates_inclusive_instants() -> None:
    points = resolve_cycle_points({
        "start": "2018-04-15T00:00:00Z",
        "end": "2018-04-15T12:00:00Z",
        "step": "PT6H",
    })
    assert [point.time for point in points] == [
        "2018-04-15T00:00:00Z",
        "2018-04-15T06:00:00Z",
        "2018-04-15T12:00:00Z",
    ]


def test_cycle_time_selects_one_instant() -> None:
    points = resolve_cycle_points(None, cycle_time="2018-04-15T06:00:00Z")
    assert [point.identifier for point in points] == ["20180415T060000Z"]


def test_partial_cycle_range_is_rejected() -> None:
    try:
        resolve_cycle_points(None, start_override="2018-04-15T00:00:00Z")
    except CycleConfigurationError as error:
        assert "missing: end, step" in str(error)
    else:
        raise AssertionError("Expected an invalid partial cycle range.")
