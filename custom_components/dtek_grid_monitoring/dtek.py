"""DTEK shutdowns client and outage classification logic."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from .const import DTEK_AJAX_PATH
from .const import DTEK_METHOD_GET_HOME_NUM
from .const import EMERGENCY_SUB_TYPES
from .const import OUTAGE_TYPE_PLANNED
from .const import REQUEST_TIMEOUT
from .const import SCHEDULED_SUB_TYPES
from .const import USER_AGENT

_CSRF_META_RE = re.compile(
    r'<meta\s+name="csrf-token"\s+content="([^"]+)"', re.IGNORECASE
)
_DTEK_DATE_RE = re.compile(r"^(\d{2}):(\d{2})\s+(\d{2})\.(\d{2})\.(\d{4})$")
_STREETS_RE = re.compile(r"DisconSchedule\.streets\s*=\s*(?=\{)")
_APOSTROPHES = str.maketrans(dict.fromkeys("’ʼ‘′`", "'"))


class DtekError(Exception):
    """Raised when DTEK data cannot be retrieved."""


def parse_dtek_date(date_str: str | None) -> datetime | None:
    """Parse the DTEK date format into a naive Europe/Kyiv datetime."""
    if not date_str:
        return None
    match = _DTEK_DATE_RE.match(date_str)
    if not match:
        return None
    hours, minutes, day, month, year = match.groups()
    return datetime(int(year), int(month), int(day), int(hours), int(minutes))


def parse_streets(html: str) -> dict[str, list[str]]:
    """Extract the city to streets directory embedded in the shutdowns page."""
    match = _STREETS_RE.search(html)
    if not match:
        return {}
    try:
        streets, _ = json.JSONDecoder().raw_decode(html, match.end())
    except ValueError:
        return {}
    return streets if isinstance(streets, dict) else {}


def _address_key(value: str) -> str:
    """Reduce a name to a form ignoring apostrophe style, spacing and case."""
    return " ".join(value.translate(_APOSTROPHES).split()).casefold()


def _match_name(names: Any, value: str) -> str | None:
    """Find the DTEK spelling of a name, preferring an exact match."""
    if value in names:
        return value
    key = _address_key(value)
    return next(
        (n for n in names if isinstance(n, str) and _address_key(n) == key), None
    )


def resolve_address(
    streets: dict[str, list[str]], city: str, street: str
) -> tuple[str, str]:
    """Return the city and street spelled exactly as DTEK lists them."""
    dtek_city = _match_name(streets, city)
    if dtek_city is None:
        return city, street
    names = streets[dtek_city]
    dtek_street = _match_name(names, street) if isinstance(names, list) else None
    return dtek_city, street if dtek_street is None else dtek_street


def normalize_houses(house: str | None, houses: list[str] | None) -> list[str]:
    """Normalize house config into a clean list of house keys."""
    if houses:
        cleaned = [h.strip() for h in houses if h and h.strip()]
        if cleaned:
            return cleaned
    if house and house.strip():
        return [house.strip()]
    return []


def has_outage_data(entry: dict[str, Any] | None) -> bool:
    """Return True if the DTEK entry carries any outage information."""
    if not entry:
        return False
    return bool(
        entry.get("sub_type")
        or entry.get("start_date")
        or entry.get("end_date")
        or entry.get("type")
    )


def is_relevant_outage(entry: dict[str, Any] | None) -> bool:
    """Return True for scheduled, emergency or planned outages."""
    if not entry:
        return False

    outage_type = entry.get("type") or ""
    if outage_type == OUTAGE_TYPE_PLANNED:
        return True

    sub_type_lower = (entry.get("sub_type") or "").lower()
    is_scheduled = any(p.lower() in sub_type_lower for p in SCHEDULED_SUB_TYPES)
    is_emergency = any(e.lower() in sub_type_lower for e in EMERGENCY_SUB_TYPES)
    return is_scheduled or is_emergency


def resolve_outage(info: dict[str, Any] | None, houses: list[str]) -> str | None:
    """Resolve the best matching house key from candidates."""
    data = (info or {}).get("data")
    if not data:
        return None

    relevant = [
        h
        for h in houses
        if has_outage_data(data.get(h)) and is_relevant_outage(data.get(h))
    ]

    if not relevant:
        return None
    if len(relevant) == 1:
        return relevant[0]

    def _earlier(best_h: str, current_h: str) -> str:
        best_end = parse_dtek_date(data[best_h].get("end_date"))
        current_end = parse_dtek_date(data[current_h].get("end_date"))
        if best_end is None:
            return current_h
        if current_end is None:
            return best_h
        return current_h if current_end < best_end else best_h

    best = relevant[0]
    for candidate in relevant[1:]:
        best = _earlier(best, candidate)
    return best


def check_is_emergency(info: dict[str, Any] | None, house: str) -> bool:
    """Return True if the outage for a house is an emergency outage."""
    data = (info or {}).get("data")
    if not data:
        raise DtekError("Power outage info missing.")
    sub_type = (data.get(house) or {}).get("sub_type") or ""
    return any(e.lower() in sub_type.lower() for e in EMERGENCY_SUB_TYPES)


def check_is_scheduled(info: dict[str, Any] | None, house: str) -> bool:
    """Return True if the outage for a house is scheduled or planned."""
    data = (info or {}).get("data")
    if not data:
        raise DtekError("Power outage info missing.")
    entry = data.get(house) or {}
    if (entry.get("type") or "") == OUTAGE_TYPE_PLANNED:
        return True
    sub_type = entry.get("sub_type") or ""
    return any(p.lower() in sub_type.lower() for p in SCHEDULED_SUB_TYPES)


class DtekClient:
    """Fetches outage information from the DTEK shutdowns site."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str) -> None:
        """Initialize the client for a given shutdowns page URL."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        parts = urlsplit(self._base_url)
        self._origin = f"{parts.scheme}://{parts.netloc}"
        self._ajax_url = f"{self._origin}{DTEK_AJAX_PATH}"

    async def async_get_info(self, city: str, street: str) -> dict[str, Any]:
        """Fetch outage info for a city/street."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT.total_seconds()):
                html = await self._async_fetch_page()
                match = _CSRF_META_RE.search(html)
                if not match:
                    raise DtekError("CSRF token not found on the shutdowns page.")
                city, street = resolve_address(parse_streets(html), city, street)
                return await self._async_post_get_home_num(match.group(1), city, street)
        except DtekError:
            raise
        except aiohttp.ClientError as err:
            raise DtekError(f"Getting info failed: {err}") from err
        except TimeoutError as err:
            raise DtekError("Getting info timed out.") from err

    async def _async_fetch_page(self) -> str:
        """Load the shutdowns page carrying the CSRF token and street list."""
        headers = {"User-Agent": USER_AGENT}
        async with self._session.get(self._base_url, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.text()

    async def _async_post_get_home_num(
        self, csrf_token: str, city: str, street: str
    ) -> dict[str, Any]:
        """POST the getHomeNum request and return the parsed response."""
        update_fact = datetime.now().strftime("%d.%m.%Y, %H:%M:%S")
        form = {
            "method": DTEK_METHOD_GET_HOME_NUM,
            "data[0][name]": "city",
            "data[0][value]": city,
            "data[1][name]": "street",
            "data[1][value]": street,
            "data[2][name]": "updateFact",
            "data[2][value]": update_fact,
        }
        headers = {
            "User-Agent": USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": csrf_token,
            "Referer": self._base_url,
            "Origin": self._origin,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        async with self._session.post(
            self._ajax_url, data=form, headers=headers
        ) as resp:
            resp.raise_for_status()
            info = await resp.json(content_type=None)

        if not isinstance(info, dict) or not info.get("result"):
            raise DtekError("DTEK returned no result for this address.")
        if "data" not in info:
            raise DtekError("DTEK response is missing outage data.")
        return info
