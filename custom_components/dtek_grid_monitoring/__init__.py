"""The DTEK Grid Monitoring integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.core import Event
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_BASE_URL
from .const import CONF_CITY
from .const import CONF_HOUSES
from .const import CONF_INITIAL_INTERVAL
from .const import CONF_INTERVAL
from .const import CONF_NAME
from .const import CONF_POWER_OFF_STATE
from .const import CONF_SOURCE_ENTITY
from .const import CONF_STREET
from .const import DEFAULT_INITIAL_INTERVAL
from .const import DEFAULT_INTERVAL
from .const import DEFAULT_POWER_OFF_STATE
from .coordinator import DtekOutageCoordinator
from .dtek import DtekClient
from .dtek import normalize_houses

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

_IGNORED_STATES = {STATE_UNAVAILABLE, STATE_UNKNOWN, None}


@dataclass
class DtekRuntimeData:
    """Runtime objects stored on the config entry."""

    coordinator: DtekOutageCoordinator
    source_entity: str
    power_off_state: str
    session: aiohttp.ClientSession


type DtekConfigEntry = ConfigEntry[DtekRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: DtekConfigEntry) -> bool:
    """Set up DTEK Grid Monitoring from a config entry."""
    data = entry.data
    options = entry.options

    houses = normalize_houses(None, data.get(CONF_HOUSES) or [])
    session = async_create_clientsession(hass)
    client = DtekClient(session, data[CONF_BASE_URL])

    coordinator = DtekOutageCoordinator(
        hass,
        entry.entry_id,
        client,
        name=data[CONF_NAME],
        city=data[CONF_CITY],
        street=data[CONF_STREET],
        houses=houses,
        initial_interval=options.get(CONF_INITIAL_INTERVAL, DEFAULT_INITIAL_INTERVAL),
        interval=options.get(CONF_INTERVAL, DEFAULT_INTERVAL),
    )

    source_entity = data[CONF_SOURCE_ENTITY]
    power_off_state = data.get(CONF_POWER_OFF_STATE, DEFAULT_POWER_OFF_STATE)

    entry.runtime_data = DtekRuntimeData(
        coordinator=coordinator,
        source_entity=source_entity,
        power_off_state=power_off_state,
        session=session,
    )
    entry.async_on_unload(session.close)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def _handle_source_change(event: Event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in _IGNORED_STATES:
            return
        if new_state.state == power_off_state:
            coordinator.start_monitoring()
        else:
            coordinator.stop_monitoring()

    entry.async_on_unload(
        async_track_state_change_event(hass, source_entity, _handle_source_change)
    )

    current = hass.states.get(source_entity)
    if current is not None and current.state == power_off_state:
        coordinator.start_monitoring()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DtekConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: DtekConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
