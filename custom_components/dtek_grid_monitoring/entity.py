"""Base entity for DTEK Grid Monitoring."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DtekOutageCoordinator


class DtekBaseEntity(CoordinatorEntity[DtekOutageCoordinator]):
    """Common base wiring device info and coordinator for all entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DtekOutageCoordinator, key: str) -> None:
        """Initialize the base entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry_id)},
            name=coordinator.friendly_name,
            manufacturer="DTEK",
            model="Grid outage monitor",
            configuration_url="https://www.dtek-oem.com.ua/ua/shutdowns",
        )
