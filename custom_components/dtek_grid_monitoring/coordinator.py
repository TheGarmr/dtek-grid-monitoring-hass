"""Coordinator driving the DTEK grid monitoring lifecycle."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .const import DTEK_TIMEZONE
from .const import EVENT_INFO_AVAILABLE
from .const import EVENT_OUTAGE_STARTED
from .const import EVENT_RESTORE_RESCHEDULED
from .const import EVENT_RESTORED
from .const import OUTAGE_KIND_EMERGENCY
from .const import OUTAGE_KIND_PLANNED
from .const import OUTAGE_KIND_SCHEDULED
from .const import OUTAGE_KIND_UNKNOWN
from .const import OUTAGE_TYPE_PLANNED
from .const import STATUS_OUTAGE_NO_INFO
from .const import STATUS_OUTAGE_WITH_INFO
from .const import STATUS_POWER_ON
from .dtek import check_is_emergency
from .dtek import check_is_scheduled
from .dtek import DtekClient
from .dtek import DtekError
from .dtek import parse_dtek_date
from .dtek import resolve_outage

_LOGGER = logging.getLogger(__name__)

_KYIV_TZ = ZoneInfo(DTEK_TIMEZONE)


def _to_utc(dtek_date: str | None) -> datetime | None:
    """Convert a DTEK date string to an aware UTC datetime."""
    naive = parse_dtek_date(dtek_date)
    if naive is None:
        return None
    return naive.replace(tzinfo=_KYIV_TZ).astimezone(dt_util.UTC)


def _capitalize(value: str | None) -> str | None:
    """Capitalize the first letter and lowercase the rest."""
    if not value:
        return None
    return value[0].upper() + value[1:].lower()


@dataclass
class OutageData:
    """Snapshot of the current monitoring state backing all entities."""

    monitoring: bool = False
    status: str = STATUS_POWER_ON
    has_info: bool = False
    reason: str | None = None
    outage_kind: str = OUTAGE_KIND_UNKNOWN
    resolved_house: str | None = None
    start_at: datetime | None = None
    expected_restore_at: datetime | None = None
    dtek_updated_at: datetime | None = None
    last_checked_at: datetime | None = None
    down_since: datetime | None = None
    restored_at: datetime | None = None
    raw_end_date: str | None = field(default=None, repr=False)
    raw_update_timestamp: str | None = field(default=None, repr=False)


class DtekOutageCoordinator(DataUpdateCoordinator[OutageData]):
    """Polls DTEK only while the source sensor reports a power outage."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        client: DtekClient,
        *,
        name: str,
        city: str,
        street: str,
        houses: list[str],
        initial_interval: int,
        interval: int,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{name}",
            update_interval=None,
        )
        self.entry_id = entry_id
        self.friendly_name = name
        self.city = city
        self.street = street
        self.houses = houses
        self._client = client
        self._initial_interval = timedelta(minutes=initial_interval)
        self._interval = timedelta(minutes=interval)
        self.data = OutageData()

    def start_monitoring(self) -> None:
        """Begin monitoring after the source sensor reports an outage."""
        if self.data.monitoring:
            return
        now = dt_util.utcnow()
        _LOGGER.info("%s: power outage detected, starting monitoring", self.friendly_name)
        self.data = OutageData(
            monitoring=True,
            status=STATUS_OUTAGE_NO_INFO,
            down_since=now,
        )
        self.update_interval = self._initial_interval
        self._fire_event(EVENT_OUTAGE_STARTED, {})
        self.async_set_updated_data(self.data)
        self.hass.async_create_task(self.async_request_refresh())

    def stop_monitoring(self) -> None:
        """Finalize monitoring after power is restored."""
        if not self.data.monitoring:
            return
        now = dt_util.utcnow()
        down_since = self.data.down_since
        duration_minutes: int | None = None
        if down_since is not None:
            duration_minutes = max(0, int((now - down_since).total_seconds() // 60))
        _LOGGER.info(
            "%s: power restored (duration: %s min)",
            self.friendly_name,
            duration_minutes,
        )
        self._fire_event(
            EVENT_RESTORED,
            {
                "restored_at": now.isoformat(),
                "down_since": down_since.isoformat() if down_since else None,
                "duration_minutes": duration_minutes,
            },
        )
        self.update_interval = None
        self.data = OutageData(
            monitoring=False,
            status=STATUS_POWER_ON,
            down_since=down_since,
            restored_at=now,
            last_checked_at=now,
        )
        self.async_set_updated_data(self.data)

    async def _async_update_data(self) -> OutageData:
        """Fetch and classify the current DTEK outage state."""
        if not self.data.monitoring:
            return self.data

        try:
            info = await self._client.async_get_info(self.city, self.street)
        except DtekError as err:
            raise UpdateFailed(str(err)) from err

        now = dt_util.utcnow()
        resolved_house = resolve_outage(info, self.houses)
        has_info = resolved_house is not None

        prev = self.data
        new = OutageData(
            monitoring=True,
            has_info=has_info,
            down_since=prev.down_since,
            last_checked_at=now,
            status=STATUS_OUTAGE_WITH_INFO if has_info else STATUS_OUTAGE_NO_INFO,
        )

        if has_info:
            entry = info["data"].get(resolved_house, {})
            new.resolved_house = resolved_house
            new.reason = _capitalize(entry.get("sub_type"))
            new.outage_kind = self._classify(info, resolved_house)
            new.start_at = _to_utc(entry.get("start_date"))
            new.expected_restore_at = _to_utc(entry.get("end_date"))
            new.dtek_updated_at = _to_utc(info.get("updateTimestamp"))
            new.raw_end_date = entry.get("end_date") or None
            new.raw_update_timestamp = info.get("updateTimestamp") or None

            self._detect_schedule_changes(prev, new)
            self.update_interval = self._interval
        else:
            self.update_interval = self._initial_interval

        return new

    def _detect_schedule_changes(self, prev: OutageData, new: OutageData) -> None:
        """Fire events when a restoration schedule appears or changes."""
        old_end = prev.raw_end_date
        new_end = new.raw_end_date
        if not new_end:
            return

        if old_end and old_end != new_end:
            _LOGGER.info(
                "%s: restore time changed %s -> %s",
                self.friendly_name,
                old_end,
                new_end,
            )
            self._fire_event(
                EVENT_RESTORE_RESCHEDULED,
                {
                    "expected_restore_at": new.expected_restore_at.isoformat()
                    if new.expected_restore_at
                    else None,
                    "expected_restore_raw": new_end,
                },
            )
        elif not old_end:
            _LOGGER.info("%s: restoration schedule appeared: %s", self.friendly_name, new_end)
            self._fire_event(
                EVENT_INFO_AVAILABLE,
                {
                    "expected_restore_at": new.expected_restore_at.isoformat()
                    if new.expected_restore_at
                    else None,
                    "expected_restore_raw": new_end,
                    "reason": new.reason,
                    "outage_kind": new.outage_kind,
                },
            )

    def _classify(self, info: dict[str, Any], house: str) -> str:
        """Classify the outage kind for the resolved house."""
        if check_is_emergency(info, house):
            return OUTAGE_KIND_EMERGENCY
        entry = info["data"].get(house, {})
        if (entry.get("type") or "") == OUTAGE_TYPE_PLANNED:
            return OUTAGE_KIND_PLANNED
        if check_is_scheduled(info, house):
            return OUTAGE_KIND_SCHEDULED
        return OUTAGE_KIND_UNKNOWN

    def _fire_event(self, event_type: str, extra: dict[str, Any]) -> None:
        """Fire a bus event carrying the address context."""
        self.hass.bus.async_fire(
            event_type,
            {
                "entry_id": self.entry_id,
                "name": self.friendly_name,
                "city": self.city,
                "street": self.street,
                "houses": self.houses,
                **extra,
            },
        )
