"""Generic time-cycle expansion for simpleWorkflow."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


class CycleConfigurationError(ValueError):
    """Raised when a cycle declaration or override is invalid."""


_DURATION = re.compile(
    r"^P(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


@dataclass(frozen=True)
class CycleContext:
    """One normalized UTC cycle and its template fields."""

    value: datetime

    @property
    def cycle_time(self) -> str:
        return self.value.isoformat(timespec="seconds").replace("+00:00", "Z")

    @property
    def cycle_id(self) -> str:
        return self.value.strftime("%Y%m%dT%H%M%SZ")

    def render_context(self) -> dict[str, str]:
        """Return generic time values available to every task template."""
        return {
            "cycle_time": self.cycle_time,
            "cycle_id": self.cycle_id,
            "cycle_yyyymmddhh": self.value.strftime("%Y%m%d%H"),
            "cycle_year": self.value.strftime("%Y"),
            "cycle_month": self.value.strftime("%m"),
            "cycle_day": self.value.strftime("%d"),
            "cycle_hour": self.value.strftime("%H"),
        }


def parse_cycle_time(value: str, *, label: str = "cycle time") -> CycleContext:
    """Parse one timezone-aware ISO-8601 timestamp as UTC."""
    if not isinstance(value, str) or not value:
        raise CycleConfigurationError(f"{label} must be a non-empty ISO-8601 timestamp.")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise CycleConfigurationError(f"Invalid {label}: {value!r}") from error
    if parsed.tzinfo is None:
        raise CycleConfigurationError(f"{label} must include a UTC offset or trailing Z.")
    return CycleContext(parsed.astimezone(timezone.utc))


def parse_iso_duration(value: str, *, label: str = "cycle step") -> timedelta:
    """Parse a positive ISO-8601 duration containing weeks through seconds."""
    if not isinstance(value, str) or not value:
        raise CycleConfigurationError(f"{label} must be a non-empty ISO-8601 duration.")
    match = _DURATION.fullmatch(value)
    if match is None:
        raise CycleConfigurationError(
            f"Invalid {label}: {value!r}; use a duration such as PT6H, P1D, or PT30M."
        )
    parts = {name: int(raw or 0) for name, raw in match.groupdict().items()}
    duration = timedelta(**parts)
    if duration <= timedelta(0):
        raise CycleConfigurationError(f"{label} must be greater than zero.")
    return duration


def validate_cycle_mapping(value: Any) -> None:
    """Validate the optional top-level ``cycle`` configuration mapping."""
    if value is None:
        return
    if not isinstance(value, dict):
        raise CycleConfigurationError("'cycle' must be a mapping.")
    unknown = set(value) - {"start", "end", "step"}
    if unknown:
        names = ", ".join(sorted(unknown))
        raise CycleConfigurationError(f"'cycle' has unsupported keys: {names}.")
    missing = [field for field in ("start", "end", "step") if field not in value]
    if missing:
        names = ", ".join(missing)
        raise CycleConfigurationError(f"'cycle' is missing required field(s): {names}.")
    parse_cycle_time(value["start"], label="cycle.start")
    parse_cycle_time(value["end"], label="cycle.end")
    parse_iso_duration(value["step"], label="cycle.step")


def resolve_cycle_contexts(
    cycle_config: dict[str, Any] | None,
    *,
    cycle_times: Iterable[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    step: str | None = None,
) -> list[CycleContext]:
    """Resolve CLI-overridden or YAML-declared cycles in chronological order.

    Explicit ``cycle_times`` select individual cycles and cannot be combined
    with range overrides. Range fields supplied on the CLI override their YAML
    counterparts one by one. An absent cycle declaration returns an empty list,
    signalling a regular non-cycling workflow.
    """
    requested = list(cycle_times or [])
    if requested:
        if any(value is not None for value in (start, end, step)):
            raise CycleConfigurationError(
                "--cycle-time cannot be combined with --from, --to, or --step."
            )
        result = [parse_cycle_time(value, label="--cycle-time") for value in requested]
        identifiers = [cycle.cycle_id for cycle in result]
        if len(set(identifiers)) != len(identifiers):
            raise CycleConfigurationError("--cycle-time values must not repeat a cycle.")
        return result

    config = cycle_config or {}
    if not config and all(value is None for value in (start, end, step)):
        return []

    raw_start = start if start is not None else config.get("start")
    raw_end = end if end is not None else config.get("end")
    raw_step = step if step is not None else config.get("step")
    missing = [
        label
        for label, value in (("start", raw_start), ("end", raw_end), ("step", raw_step))
        if value is None
    ]
    if missing:
        raise CycleConfigurationError("Cycle range requires " + ", ".join(missing) + ".")

    first = parse_cycle_time(raw_start, label="cycle start")
    last = parse_cycle_time(raw_end, label="cycle end")
    interval = parse_iso_duration(raw_step, label="cycle step")
    if first.value > last.value:
        raise CycleConfigurationError("cycle start must not be later than cycle end.")

    result: list[CycleContext] = []
    current = first.value
    while current <= last.value:
        result.append(CycleContext(current))
        if len(result) > 100_000:
            raise CycleConfigurationError("cycle expansion exceeds 100000 cycles.")
        current += interval
    return result
