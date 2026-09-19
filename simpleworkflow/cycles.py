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

SUPPORTED_CYCLE_SCOPES = frozenset({"all", "first", "not_first", "last", "not_last"})


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _cycle_id(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%SZ")


def _time_context(prefix: str, value: datetime | None) -> dict[str, str]:
    if value is None:
        return {
            f"{prefix}_cycle_time": "",
            f"{prefix}_cycle_id": "",
            f"{prefix}_cycle_yyyymmddhh": "",
            f"{prefix}_cycle_year": "",
            f"{prefix}_cycle_month": "",
            f"{prefix}_cycle_day": "",
            f"{prefix}_cycle_hour": "",
        }
    return {
        f"{prefix}_cycle_time": _iso(value),
        f"{prefix}_cycle_id": _cycle_id(value),
        f"{prefix}_cycle_yyyymmddhh": value.strftime("%Y%m%d%H"),
        f"{prefix}_cycle_year": value.strftime("%Y"),
        f"{prefix}_cycle_month": value.strftime("%m"),
        f"{prefix}_cycle_day": value.strftime("%d"),
        f"{prefix}_cycle_hour": value.strftime("%H"),
    }


@dataclass(frozen=True)
class CycleContext:
    """One normalized UTC cycle and its position in the declared campaign."""

    value: datetime
    index: int = 0
    count: int = 1
    previous_value: datetime | None = None
    next_value: datetime | None = None

    @property
    def cycle_time(self) -> str:
        return _iso(self.value)

    @property
    def cycle_id(self) -> str:
        return _cycle_id(self.value)

    @property
    def is_first(self) -> bool:
        return self.index == 0

    @property
    def is_last(self) -> bool:
        return self.index == self.count - 1

    def render_context(self) -> dict[str, str]:
        """Return generic time and campaign-position values for task templates.

        Context values are strings because they are consumed by Python-format
        templates. Missing previous/next cycles are represented by the empty
        string, and booleans use lowercase ``true``/``false``.
        """
        context = {
            "cycle_time": self.cycle_time,
            "cycle_id": self.cycle_id,
            "cycle_yyyymmddhh": self.value.strftime("%Y%m%d%H"),
            "cycle_year": self.value.strftime("%Y"),
            "cycle_month": self.value.strftime("%m"),
            "cycle_day": self.value.strftime("%d"),
            "cycle_hour": self.value.strftime("%H"),
            "cycle_index": str(self.index),
            "cycle_count": str(self.count),
            "is_first": "true" if self.is_first else "false",
            "is_last": "true" if self.is_last else "false",
            "cycle_is_first": "true" if self.is_first else "false",
            "cycle_is_last": "true" if self.is_last else "false",
        }
        context.update(_time_context("previous", self.previous_value))
        context.update(_time_context("next", self.next_value))
        return context


def cycle_scope_matches(scope: str | None, cycle: CycleContext) -> bool:
    """Return whether a task scope applies to ``cycle``."""
    normalized = scope or "all"
    if normalized not in SUPPORTED_CYCLE_SCOPES:
        supported = ", ".join(sorted(SUPPORTED_CYCLE_SCOPES))
        raise CycleConfigurationError(
            f"unsupported cycle_scope {normalized!r}; use one of: {supported}."
        )
    return {
        "all": True,
        "first": cycle.is_first,
        "not_first": not cycle.is_first,
        "last": cycle.is_last,
        "not_last": not cycle.is_last,
    }[normalized]


def parse_cycle_time(value: Any, *, label: str = "cycle time") -> CycleContext:
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


def parse_iso_duration(value: Any, *, label: str = "cycle step") -> timedelta:
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
    unknown = set(value) - {"start", "end", "duration", "step", "interval"}
    if unknown:
        names = ", ".join(sorted(unknown))
        raise CycleConfigurationError(f"'cycle' has unsupported keys: {names}.")
    if "start" not in value:
        raise CycleConfigurationError("'cycle' is missing required field(s): start.")

    end_fields = [field for field in ("end", "duration") if field in value]
    if not end_fields:
        raise CycleConfigurationError(
            "'cycle' is missing required field: end or duration."
        )
    if len(end_fields) > 1:
        raise CycleConfigurationError(
            "'cycle' must define only one of 'end' or 'duration'."
        )

    interval_fields = [field for field in ("step", "interval") if field in value]
    if not interval_fields:
        raise CycleConfigurationError(
            "'cycle' is missing required field: step or interval."
        )
    if len(interval_fields) > 1:
        raise CycleConfigurationError(
            "'cycle' must define only one of 'step' or 'interval'."
        )

    parse_cycle_time(value["start"], label="cycle.start")
    if "end" in value:
        parse_cycle_time(value["end"], label="cycle.end")
    else:
        parse_iso_duration(value["duration"], label="cycle.duration")
    parse_iso_duration(value[interval_fields[0]], label=f"cycle.{interval_fields[0]}")


def _resolved_range(
    config: dict[str, Any],
    *,
    start: str | None = None,
    end: str | None = None,
    step: str | None = None,
) -> tuple[str, str, str]:
    """Resolve one inclusive range while preserving compatible field aliases."""
    if config:
        validate_cycle_mapping(config)

    raw_start = start if start is not None else config.get("start")
    raw_step = step
    if raw_step is None:
        raw_step = config.get("step", config.get("interval"))

    raw_end: Any = end
    if raw_end is None:
        if "end" in config:
            raw_end = config["end"]
        elif "duration" in config and raw_start is not None:
            if not isinstance(raw_start, str):
                raise CycleConfigurationError("Cycle range start must be a string.")
            first = parse_cycle_time(raw_start, label="cycle start")
            duration = parse_iso_duration(config["duration"], label="cycle duration")
            raw_end = _iso(first.value + duration)

    missing = [
        label
        for label, value in (
            ("start", raw_start),
            ("end or duration", raw_end),
            ("step or interval", raw_step),
        )
        if value is None
    ]
    if missing:
        raise CycleConfigurationError("Cycle range requires " + ", ".join(missing) + ".")
    if (
        not isinstance(raw_start, str)
        or not isinstance(raw_end, str)
        or not isinstance(raw_step, str)
    ):
        raise CycleConfigurationError(
            "Cycle range start, end/duration, and step/interval must resolve to strings."
        )
    return raw_start, raw_end, raw_step


def _range_values(start: str, end: str, step: str) -> list[datetime]:
    first = parse_cycle_time(start, label="cycle start")
    last = parse_cycle_time(end, label="cycle end")
    interval = parse_iso_duration(step, label="cycle step")
    if first.value > last.value:
        raise CycleConfigurationError("cycle start must not be later than cycle end.")

    values: list[datetime] = []
    current = first.value
    while current <= last.value:
        values.append(current)
        if len(values) > 100_000:
            raise CycleConfigurationError("cycle expansion exceeds 100000 cycles.")
        current += interval
    return values


def _positioned(values: list[datetime]) -> list[CycleContext]:
    count = len(values)
    return [
        CycleContext(
            value=value,
            index=index,
            count=count,
            previous_value=values[index - 1] if index else None,
            next_value=values[index + 1] if index + 1 < count else None,
        )
        for index, value in enumerate(values)
    ]


def resolve_cycle_contexts(
    cycle_config: dict[str, Any] | None,
    *,
    cycle_times: Iterable[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    step: str | None = None,
) -> list[CycleContext]:
    """Resolve CLI-overridden or YAML-declared cycles in chronological order.

    Ranges are inclusive at both endpoints. Explicit ``cycle_times`` select
    individual cycles and cannot be combined with range overrides. When the
    workflow declares a range, explicit selections retain their position in
    that full campaign so selectors such as ``not_last`` keep their meaning.
    """
    requested = list(cycle_times or [])
    if requested:
        if any(value is not None for value in (start, end, step)):
            raise CycleConfigurationError(
                "--cycle-time cannot be combined with --from, --to, or --step."
            )
        parsed = [parse_cycle_time(value, label="--cycle-time") for value in requested]
        identifiers = [cycle.cycle_id for cycle in parsed]
        if len(set(identifiers)) != len(identifiers):
            raise CycleConfigurationError("--cycle-time values must not repeat a cycle.")

        if cycle_config:
            raw_start, raw_end, raw_step = _resolved_range(cycle_config)
            full = _positioned(_range_values(raw_start, raw_end, raw_step))
            by_id = {cycle.cycle_id: cycle for cycle in full}
            missing = [cycle.cycle_id for cycle in parsed if cycle.cycle_id not in by_id]
            if missing:
                raise CycleConfigurationError(
                    "--cycle-time is outside the declared cycle range: " + ", ".join(missing)
                )
            return [by_id[cycle.cycle_id] for cycle in parsed]

        return _positioned([cycle.value for cycle in parsed])

    config = cycle_config or {}
    if not config and all(value is None for value in (start, end, step)):
        return []

    raw_start, raw_end, raw_step = _resolved_range(
        config,
        start=start,
        end=end,
        step=step,
    )
    return _positioned(_range_values(raw_start, raw_end, raw_step))
