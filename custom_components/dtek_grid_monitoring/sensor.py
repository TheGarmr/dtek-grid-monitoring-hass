"""Sensors for DTEK Grid Monitoring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import DtekConfigEntry
from .const import DOMAIN
from .const import OUTAGE_KIND_EMERGENCY
from .const import OUTAGE_KIND_PLANNED
from .const import OUTAGE_KIND_SCHEDULED
from .const import OUTAGE_KIND_UNKNOWN
from .const import SCHEDULE_STATE_NO_OUTAGES
from .const import SCHEDULE_STATE_NOT_PUBLISHED
from .const import SCHEDULE_STATE_SCHEDULED
from .const import STATUS_OUTAGE_NO_INFO
from .const import STATUS_OUTAGE_WITH_INFO
from .const import STATUS_POWER_ON
from .coordinator import DtekOutageCoordinator
from .coordinator import DtekScheduleCoordinator
from .coordinator import OutageData
from .entity import DtekBaseEntity
from .schedule import DaySchedule
from .schedule import kyiv_today
from .schedule import next_outage
from .schedule import ScheduledOutage


@dataclass(frozen=True, kw_only=True)
class DtekSensorDescription(SensorEntityDescription):
    """Describes a DTEK sensor."""

    value_fn: Callable[[OutageData], str | datetime | None]


SENSORS: tuple[DtekSensorDescription, ...] = (
    DtekSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=[STATUS_POWER_ON, STATUS_OUTAGE_NO_INFO, STATUS_OUTAGE_WITH_INFO],
        value_fn=lambda d: d.status,
    ),
    DtekSensorDescription(
        key="reason",
        translation_key="reason",
        value_fn=lambda d: d.reason,
    ),
    DtekSensorDescription(
        key="outage_kind",
        translation_key="outage_kind",
        device_class=SensorDeviceClass.ENUM,
        options=[
            OUTAGE_KIND_PLANNED,
            OUTAGE_KIND_SCHEDULED,
            OUTAGE_KIND_EMERGENCY,
            OUTAGE_KIND_UNKNOWN,
        ],
        value_fn=lambda d: d.outage_kind if d.has_info else None,
    ),
    DtekSensorDescription(
        key="outage_start",
        translation_key="outage_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.start_at,
    ),
    DtekSensorDescription(
        key="expected_restore",
        translation_key="expected_restore",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.expected_restore_at,
    ),
    DtekSensorDescription(
        key="dtek_updated",
        translation_key="dtek_updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.dtek_updated_at,
    ),
    DtekSensorDescription(
        key="last_checked",
        translation_key="last_checked",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.last_checked_at,
    ),
)


@dataclass(frozen=True, kw_only=True)
class DtekScheduleSensorDescription(SensorEntityDescription):
    """Describes a DTEK schedule sensor for a day relative to today."""

    day_offset: int


SCHEDULE_SENSORS: tuple[DtekScheduleSensorDescription, ...] = tuple(
    DtekScheduleSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENUM,
        options=[
            SCHEDULE_STATE_SCHEDULED,
            SCHEDULE_STATE_NO_OUTAGES,
            SCHEDULE_STATE_NOT_PUBLISHED,
        ],
        day_offset=day_offset,
    )
    for key, day_offset in (("schedule_today", 0), ("schedule_tomorrow", 1))
)

NEXT_OUTAGE_KEY = "next_scheduled_outage"

SCHEDULE_ENTITY_KEYS: tuple[str, ...] = (
    *(desc.key for desc in SCHEDULE_SENSORS),
    NEXT_OUTAGE_KEY,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DtekConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the DTEK sensors."""
    coordinator = entry.runtime_data.coordinator
    schedule_coordinator = entry.runtime_data.schedule_coordinator
    entities: list[SensorEntity] = [DtekSensor(coordinator, desc) for desc in SENSORS]
    if schedule_coordinator is not None:
        entities.extend(
            DtekScheduleSensor(schedule_coordinator, desc) for desc in SCHEDULE_SENSORS
        )
        entities.append(DtekNextOutageSensor(schedule_coordinator))
    else:
        _remove_schedule_entities(hass, entry)
    async_add_entities(entities)


def _remove_schedule_entities(hass: HomeAssistant, entry: DtekConfigEntry) -> None:
    """Drop schedule sensors left over from when monitoring was enabled."""
    registry = er.async_get(hass)
    for key in SCHEDULE_ENTITY_KEYS:
        entity_id = registry.async_get_entity_id(
            Platform.SENSOR, DOMAIN, f"{entry.entry_id}_{key}"
        )
        if entity_id is not None:
            registry.async_remove(entity_id)


class DtekSensor(DtekBaseEntity[DtekOutageCoordinator], SensorEntity):
    """A single DTEK-derived sensor."""

    entity_description: DtekSensorDescription

    def __init__(
        self, coordinator: DtekOutageCoordinator, description: DtekSensorDescription
    ) -> None:
        """Initialize the sensor from its description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | datetime | None:
        """Return the current value from the coordinator snapshot."""
        return self.entity_description.value_fn(self.coordinator.data)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Write state on every coordinator update."""
        self.async_write_ha_state()


class DtekScheduleSensor(DtekBaseEntity[DtekScheduleCoordinator], SensorEntity):
    """Whether DTEK scheduled outages for a day, with the windows as attributes."""

    entity_description: DtekScheduleSensorDescription

    def __init__(
        self,
        coordinator: DtekScheduleCoordinator,
        description: DtekScheduleSensorDescription,
    ) -> None:
        """Initialize the sensor from its description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    def _schedule(self) -> DaySchedule | None:
        """Return the published schedule for this sensor's day, if any."""
        snapshot = self.coordinator.data
        if snapshot is None:
            return None
        day = kyiv_today() + timedelta(days=self.entity_description.day_offset)
        return snapshot.days.get(day)

    @property
    def native_value(self) -> str | None:
        """Return whether outages are scheduled for the day."""
        snapshot = self.coordinator.data
        if snapshot is None or not snapshot.groups:
            return None
        schedule = self._schedule()
        if schedule is None:
            return SCHEDULE_STATE_NOT_PUBLISHED
        if schedule.has_outages:
            return SCHEDULE_STATE_SCHEDULED
        return SCHEDULE_STATE_NO_OUTAGES

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the outage windows of the day."""
        snapshot = self.coordinator.data
        schedule = self._schedule()
        return {
            "date": schedule.day.isoformat() if schedule else None,
            "summary": schedule.summary if schedule else "",
            "groups": schedule.groups_as_dicts() if schedule else [],
            "updated": snapshot.updated if snapshot else None,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Write state on every coordinator update."""
        self.async_write_ha_state()


class DtekNextOutageSensor(DtekBaseEntity[DtekScheduleCoordinator], SensorEntity):
    """Start of the next scheduled outage of any group of the address."""

    _attr_translation_key = NEXT_OUTAGE_KEY
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: DtekScheduleCoordinator) -> None:
        """Initialize the next scheduled outage sensor."""
        super().__init__(coordinator, NEXT_OUTAGE_KEY)

    def _outage(self) -> ScheduledOutage | None:
        """Return the next scheduled outage, if any is published."""
        return next_outage(self.coordinator.data, dt_util.utcnow())

    @property
    def native_value(self) -> datetime | None:
        """Return when the next scheduled outage starts."""
        outage = self._outage()
        return outage.start if outage else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the end, group and kind of the next scheduled outage."""
        outage = self._outage()
        return {
            "end": outage.end if outage else None,
            "summary": outage.summary if outage else "",
            "group": outage.group if outage else None,
            "name": outage.name if outage else None,
            "type": outage.type if outage else None,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Write state on every coordinator update."""
        self.async_write_ha_state()
