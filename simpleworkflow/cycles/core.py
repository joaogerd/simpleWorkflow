from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

_DURATION_RE = re.compile(
    r"^P(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


class CycleConfigurationError(ValueError):
    """Raised when a workflow cycle definition is invalid."""


@dataclass(frozen=True)
class CyclePoint:
    """One normalized UTC cycle instant."""

    value: datetime

    @property
    def time(self) -> str:
        return format_cycle_time(self.value)

    @property
    def identifier(self) -> str:
        return self.value.strftime("%Y%m%dT%H%M%SZ")


def parse_cycle_time(value: str | datetime, *, field: str = "cycle time") -> datetime:
    """Parse a timezone-aware ISO timestamp or normalize a YAML datetime."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as error:
            raise CycleConfigurationError(
                f"{field} must be an ISO-8601 timestamp: {value!r}."
            ) from error
    else:
        raise CycleConfigurationError(f"{field} must be a non-empty ISO-8601 timestamp.")

    if parsed.tzinfo is None:
        raise CycleConfigurationError(f"{field} must include a UTC offset or trailing Z.")
    return parsed.astimezone(UTC)


def format_cycle_time(value: datetime) -> str:
    """Format one instant for command rendering and provenance."""
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_cycle_step(value: str, *, field: str = "cycle.step") -> timedelta:
    """Parse a positive fixed ISO-8601 duration without months or years."""
    if not isinstance(value, str) or not value:
        raise CycleConfigurationError(f"{field} must be a non-empty ISO-8601 duration.")

    match = _DURATION_RE.fullmatch(value)
    if match is None or not any(part is not None for part in match.groupdict().values()):
        raise CycleConfigurationError(
            f"{field} must be a fixed ISO-8601 duration such as PT6H, P1D or P1W."
        )

    step = timedelta(**{key: int(part or 0) for key, part in match.groupdict().items()})
    if step <= timedelta(0):
        raise CycleConfigurationError(f"{field} must be greater than zero.")
    return step


def validate_cycle_mapping(value: Any) -> None:
    """Validate the optional top-level cycle mapping."""
    if not isinstance(value, dict):
        raise CycleConfigurationError("'cycle' must be a mapping.")

    allowed = {"start", "end", "step"}
    unknown = set(value) - allowed
    if unknown:
        raise CycleConfigurationError(
            "'cycle' has unsupported keys: " + ", ".join(sorted(unknown)) + "."
        )

    missing = sorted(allowed - set(value))
    if missing:
        raise CycleConfigurationError(
            "'cycle' must define start, end and step; missing: " + ", ".join(missing) + "."
        )

    start = parse_cycle_time(value["start"], field="cycle.start")
    end = parse_cycle_time(value["end"], field="cycle.end")
    if end < start:
        raise CycleConfigurationError("cycle.end must not be earlier than cycle.start.")
    parse_cycle_step(value["step"])


def resolve_cycle_points(
    cycle: dict[str, Any] | None,
    *,
    start_override: str | None = None,
    end_override: str | None = None,
    step_override: str | None = None,
    cycle_time: str | None = None,
) -> list[CyclePoint]:
    """Resolve documented or command-line cycle settings into ordered instants."""
    if cycle_time is not None:
        if any(value is not None for value in (start_override, end_override, step_override)):
            raise CycleConfigurationError(
                "--cycle-time cannot be combined with --from, --to or --step."
            )
        return [CyclePoint(parse_cycle_time(cycle_time, field="--cycle-time"))]

    if cycle is not None:
        validate_cycle_mapping(cycle)
    source = cycle or {}
    start_value = start_override if start_override is not None else source.get("start")
    end_value = end_override if end_override is not None else source.get("end")
    step_value = step_override if step_override is not None else source.get("step")

    if start_value is None and end_value is None and step_value is None:
        return []

    missing = [
        name
        for name, value in (("start", start_value), ("end", end_value), ("step", step_value))
        if value is None
    ]
    if missing:
        raise CycleConfigurationError(
            "A cycle requires start, end and step after applying CLI overrides; missing: "
            + ", ".join(missing)
            + "."
        )

    start = parse_cycle_time(start_value, field="cycle.start")
    end = parse_cycle_time(end_value, field="cycle.end")
    if end < start:
        raise CycleConfigurationError("cycle.end must not be earlier than cycle.start.")
    step = parse_cycle_step(step_value)

    points: list[CyclePoint] = []
    current = start
    while current <= end:
        points.append(CyclePoint(current))
        current += step
    return points
