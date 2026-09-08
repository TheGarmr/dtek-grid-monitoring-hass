"""Constants for the DTEK Grid Monitoring integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "dtek_grid_monitoring"

CONF_NAME: Final = "name"
CONF_BASE_URL: Final = "base_url"
CONF_CITY: Final = "city"
CONF_STREET: Final = "street"
CONF_HOUSES: Final = "houses"
CONF_SOURCE_ENTITY: Final = "source_entity"
CONF_POWER_OFF_STATE: Final = "power_off_state"
CONF_INITIAL_INTERVAL: Final = "initial_interval"
CONF_INTERVAL: Final = "interval"

DEFAULT_BASE_URL: Final = "https://www.dtek-oem.com.ua/ua/shutdowns"
DEFAULT_SOURCE_ENTITY: Final = "binary_sensor.deye_grid"
DEFAULT_POWER_OFF_STATE: Final = "off"
DEFAULT_INITIAL_INTERVAL: Final = 2
DEFAULT_INTERVAL: Final = 10

DTEK_TIMEZONE: Final = "Europe/Kyiv"

DTEK_AJAX_PATH: Final = "/ua/ajax"
DTEK_METHOD_GET_HOME_NUM: Final = "getHomeNum"
REQUEST_TIMEOUT: Final = timedelta(seconds=30)
USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

OUTAGE_TYPE_PLANNED: Final = "1"
OUTAGE_TYPE_SUBTYPE_DRIVEN: Final = "2"

SCHEDULED_SUB_TYPES: Final = (
    "Стабілізаційне відключення (Згідно графіку погодинних відключень)",
    "планові ремонтні роботи",
    "Приєднання нового клієнту до електричних мереж",
)

EMERGENCY_SUB_TYPES: Final = (
    "Екстренні відключення (Аварійне без застосування графіку погодинних відключень)",
    "аварійні ремонтні роботи",
)

OUTAGE_KIND_PLANNED: Final = "planned"
OUTAGE_KIND_SCHEDULED: Final = "scheduled"
OUTAGE_KIND_EMERGENCY: Final = "emergency"
OUTAGE_KIND_UNKNOWN: Final = "unknown"

STATUS_POWER_ON: Final = "power_on"
STATUS_OUTAGE_NO_INFO: Final = "outage_no_info"
STATUS_OUTAGE_WITH_INFO: Final = "outage_with_info"

EVENT_OUTAGE_STARTED: Final = f"{DOMAIN}_outage_started"
EVENT_INFO_AVAILABLE: Final = f"{DOMAIN}_info_available"
EVENT_RESTORE_RESCHEDULED: Final = f"{DOMAIN}_restore_rescheduled"
EVENT_RESTORED: Final = f"{DOMAIN}_restored"
