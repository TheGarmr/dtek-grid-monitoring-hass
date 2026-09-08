"""Sensors for DTEK Grid Monitoring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.core import callback
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DtekConfigEntry
from .const import OUTAGE_KIND_EMERGENCY
from .const import OUTAGE_KIND_PLANNED
from .const import OUTAGE_KIND_SCHEDULED
from .const import OUTAGE_KIND_UNKNOWN
from .const import STATUS_OUTAGE_NO_INFO
from .const import STATUS_OUTAGE_WITH_INFO
from .const import STATUS_POWER_ON
from .coordinator import DtekOutageCoordinator
from .coordinator import OutageData
from .entity import DtekBaseEntity


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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DtekConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the DTEK sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(DtekSensor(coordinator, desc) for desc in SENSORS)


class DtekSensor(DtekBaseEntity, SensorEntity):
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
