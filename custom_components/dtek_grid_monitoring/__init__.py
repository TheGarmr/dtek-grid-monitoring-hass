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
from homeassistant.core import CALLBACK_TYPE
from homeassistant.core import Event
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_BASE_URL
from .const import CONF_CITY
from .const import CONF_HOUSES
from .const import CONF_INITIAL_INTERVAL
from .const import CONF_INTERVAL
from .const import CONF_NAME
from .const import CONF_POWER_OFF_STATE
from .const import CONF_RELAY_ENTITY
from .const import CONF_RELAY_OFF_STATE
from .const import CONF_SOURCE_ENTITY
from .const import CONF_STREET
from .const import DEFAULT_INITIAL_INTERVAL
from .const import DEFAULT_INTERVAL
from .const import DEFAULT_POWER_OFF_STATE
from .const import DEFAULT_RELAY_OFF_STATE
from .const import RELAY_GRACE_PERIOD
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
    relay_entity: str | None = options.get(CONF_RELAY_ENTITY) or None
    relay_off_state = options.get(CONF_RELAY_OFF_STATE, DEFAULT_RELAY_OFF_STATE)

    entry.runtime_data = DtekRuntimeData(
        coordinator=coordinator,
        source_entity=source_entity,
        power_off_state=power_off_state,
        session=session,
    )
    entry.async_on_unload(session.close)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    cancel_pending: CALLBACK_TYPE | None = None

    def _source_off() -> bool | None:
        state = hass.states.get(source_entity)
        if state is None or state.state in _IGNORED_STATES:
            return None
        return state.state == power_off_state

    def _relay_tripped() -> bool:
        if relay_entity is None:
            return False
        state = hass.states.get(relay_entity)
        return state is not None and state.state == relay_off_state

    @callback
    def _cancel_pending() -> None:
        nonlocal cancel_pending
        if cancel_pending is not None:
            cancel_pending()
            cancel_pending = None

    @callback
    def _evaluate(*_: object) -> None:
        _cancel_pending()
        source_off = _source_off()
        if source_off is None:
            return
        if source_off and not _relay_tripped():
            coordinator.start_monitoring()
        else:
            coordinator.stop_monitoring()

    @callback
    def _schedule_evaluation() -> None:
        nonlocal cancel_pending
        _cancel_pending()
        cancel_pending = async_call_later(hass, RELAY_GRACE_PERIOD, _evaluate)

    @callback
    def _handle_source_change(event: Event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in _IGNORED_STATES:
            return
        if relay_entity is not None and new_state.state == power_off_state:
            _schedule_evaluation()
        else:
            _evaluate()

    @callback
    def _handle_relay_change(event: Event) -> None:
        if _source_off():
            _schedule_evaluation()

    entry.async_on_unload(_cancel_pending)
    entry.async_on_unload(
        async_track_state_change_event(hass, source_entity, _handle_source_change)
    )
    if relay_entity is not None:
        entry.async_on_unload(
            async_track_state_change_event(hass, relay_entity, _handle_relay_change)
        )

    _evaluate()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DtekConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: DtekConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
