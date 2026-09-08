"""Binary sensor for DTEK Grid Monitoring."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import callback
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DtekConfigEntry
from .coordinator import DtekOutageCoordinator
from .entity import DtekBaseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DtekConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the grid power binary sensor."""
    async_add_entities([DtekGridPowerBinarySensor(entry.runtime_data.coordinator)])


class DtekGridPowerBinarySensor(DtekBaseEntity, BinarySensorEntity):
    """Grid power presence: on when there is power, off during an outage."""

    _attr_translation_key = "grid_power"
    _attr_device_class = BinarySensorDeviceClass.POWER

    def __init__(self, coordinator: DtekOutageCoordinator) -> None:
        """Initialize the grid power binary sensor."""
        super().__init__(coordinator, "grid_power")

    @property
    def is_on(self) -> bool:
        """Return True when grid power is present."""
        return not self.coordinator.data.monitoring

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes for the outage."""
        data = self.coordinator.data
        return {
            "down_since": data.down_since,
            "has_dtek_info": data.has_info,
            "resolved_house": data.resolved_house,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Write state on every coordinator update."""
        self.async_write_ha_state()
