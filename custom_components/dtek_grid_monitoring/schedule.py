"""Parsing of the DTEK hourly outage schedules."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .const import DTEK_TIMEZONE
from .const import INTERVAL_TYPE_OUTAGE
from .const import INTERVAL_TYPE_POSSIBLE

_KYIV_TZ = ZoneInfo(DTEK_TIMEZONE)

_SLOT_MINUTES = 30
_HOURS = range(1, 25)

_HOUR_STATES: dict[str, tuple[str | None, str | None]] = {
    "yes": (None, None),
    "no": (INTERVAL_TYPE_OUTAGE, INTERVAL_TYPE_OUTAGE),
    "first": (INTERVAL_TYPE_OUTAGE, None),
    "second": (None, INTERVAL_TYPE_OUTAGE),
    "maybe": (INTERVAL_TYPE_POSSIBLE, INTERVAL_TYPE_POSSIBLE),
    "mfirst": (INTERVAL_TYPE_POSSIBLE, None),
    "msecond": (None, INTERVAL_TYPE_POSSIBLE),
}


def kyiv_today() -> date:
    """Return the current date in the DTEK timezone."""
    return datetime.now(_KYIV_TZ).date()


def _format_minutes(minutes: int) -> str:
    """Format minutes from midnight as HH:MM, keeping 24:00 for the day end."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass(frozen=True)
class OutageInterval:
    """A continuous outage window, in minutes from local midnight."""

    start: int
    end: int
    type: str

    def as_dict(self) -> dict[str, str]:
        """Return the interval in an event/attribute friendly form."""
        return {
            "start": _format_minutes(self.start),
            "end": _format_minutes(self.end),
            "type": self.type,
        }

    def as_text(self) -> str:
        """Return the interval as text, possible outages prefixed with a tilde."""
        text = f"{_format_minutes(self.start)}–{_format_minutes(self.end)}"
        return f"~{text}" if self.type == INTERVAL_TYPE_POSSIBLE else text


@dataclass(frozen=True)
class GroupSchedule:
    """Outage windows of one schedule group for a single day."""

    group: str
    name: str
    intervals: tuple[OutageInterval, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return the group schedule in an event/attribute friendly form."""
        return {
            "group": self.group,
            "name": self.name,
            "intervals": [interval.as_dict() for interval in self.intervals],
        }


@dataclass(frozen=True)
class DaySchedule:
    """Schedule of every group of the address for a single day."""

    day: date
    groups: tuple[GroupSchedule, ...] = ()

    @property
    def has_outages(self) -> bool:
        """Return True if any group has an outage window on this day."""
        return any(group.intervals for group in self.groups)

    @property
    def summary(self) -> str:
        """Return a one-line-per-group text of the outage windows."""
        if not self.has_outages:
            return ""
        return "\n".join(
            f"{group.name}: {', '.join(i.as_text() for i in group.intervals) or '—'}"
            for group in self.groups
        )

    def groups_as_dicts(self) -> list[dict[str, Any]]:
        """Return all group schedules in an event/attribute friendly form."""
        return [group.as_dict() for group in self.groups]


@dataclass(frozen=True)
class ScheduleSnapshot:
    """Everything DTEK currently publishes about the address schedule."""

    groups: tuple[str, ...]
    days: dict[date, DaySchedule]
    updated: str | None


def house_groups(info: dict[str, Any] | None, houses: list[str]) -> tuple[str, ...]:
    """Return the schedule groups of the configured houses, in DTEK order."""
    data = (info or {}).get("data")
    if not isinstance(data, dict):
        return ()

    groups: list[str] = []
    for house in houses:
        reasons = (data.get(house) or {}).get("sub_type_reason") or []
        if isinstance(reasons, str):
            reasons = [reasons]
        for group in reasons:
            if group not in groups:
                groups.append(group)
    return tuple(groups)


def _parse_day(raw_timestamp: str) -> date | None:
    """Convert a DTEK day key (unix time of Kyiv midnight) into a date."""
    try:
        return datetime.fromtimestamp(int(raw_timestamp), _KYIV_TZ).date()
    except (ValueError, OverflowError, OSError):
        return None


def _build_intervals(hours: dict[str, Any]) -> tuple[OutageInterval, ...]:
    """Merge the hourly DTEK states into continuous outage windows."""
    slots: list[str | None] = []
    for hour in _HOURS:
        slots.extend(_HOUR_STATES.get(str(hours.get(str(hour))), (None, None)))

    intervals: list[OutageInterval] = []
    start = 0
    for index in range(1, len(slots) + 1):
        if index < len(slots) and slots[index] == slots[start]:
            continue
        kind = slots[start]
        if kind is not None:
            intervals.append(
                OutageInterval(start * _SLOT_MINUTES, index * _SLOT_MINUTES, kind)
            )
        start = index
    return tuple(intervals)


def parse_schedule(
    info: dict[str, Any] | None, houses: list[str]
) -> ScheduleSnapshot | None:
    """Parse the fact schedule of a getHomeNum response for the given houses."""
    fact = (info or {}).get("fact")
    if not isinstance(fact, dict):
        return None

    groups = house_groups(info, houses)
    preset = info.get("preset")
    names = preset.get("sch_names") if isinstance(preset, dict) else None
    if not isinstance(names, dict):
        names = {}

    days: dict[date, DaySchedule] = {}
    fact_data = fact.get("data")
    if groups and isinstance(fact_data, dict):
        for raw_timestamp, by_group in fact_data.items():
            day = _parse_day(raw_timestamp)
            if day is None or not isinstance(by_group, dict):
                continue
            days[day] = DaySchedule(
                day,
                tuple(
                    GroupSchedule(
                        group,
                        names.get(group) or group,
                        _build_intervals(by_group[group]),
                    )
                    for group in groups
                    if isinstance(by_group.get(group), dict)
                ),
            )

    return ScheduleSnapshot(groups, days, fact.get("update") or None)


@dataclass(frozen=True)
class ScheduledOutage:
    """A continuous outage window of one group, possibly spanning midnight."""

    start: datetime
    end: datetime
    type: str
    group: str
    name: str

    @property
    def summary(self) -> str:
        """Return the window as local HH:MM–HH:MM text."""
        return f"{self.start:%H:%M}–{self.end:%H:%M}"


def _group_outages(snapshot: ScheduleSnapshot, group: str) -> list[ScheduledOutage]:
    """Return the outage windows of a group, merged across adjacent days."""
    outages: list[ScheduledOutage] = []
    for day in sorted(snapshot.days):
        midnight = datetime.combine(day, time.min, _KYIV_TZ)
        for group_schedule in snapshot.days[day].groups:
            if group_schedule.group != group:
                continue
            for interval in group_schedule.intervals:
                start = midnight + timedelta(minutes=interval.start)
                end = midnight + timedelta(minutes=interval.end)
                last = outages[-1] if outages else None
                if last is None or start > last.end:
                    outages.append(
                        ScheduledOutage(
                            start,
                            end,
                            interval.type,
                            group_schedule.group,
                            group_schedule.name,
                        )
                    )
                    continue
                confirmed = INTERVAL_TYPE_OUTAGE in (last.type, interval.type)
                outages[-1] = replace(
                    last,
                    end=max(last.end, end),
                    type=INTERVAL_TYPE_OUTAGE if confirmed else INTERVAL_TYPE_POSSIBLE,
                )
    return outages


def next_outage(
    snapshot: ScheduleSnapshot | None, now: datetime
) -> ScheduledOutage | None:
    """Return the earliest scheduled outage of any group starting after now."""
    if snapshot is None:
        return None
    upcoming = [
        outage
        for group in snapshot.groups
        for outage in _group_outages(snapshot, group)
        if outage.start > now
    ]
    return min(upcoming, key=lambda outage: outage.start, default=None)
