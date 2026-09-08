"""DTEK shutdowns client and outage classification logic."""

from __future__ import annotations

import asyncio
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
                csrf_token = await self._async_fetch_csrf()
                return await self._async_post_get_home_num(csrf_token, city, street)
        except DtekError:
            raise
        except aiohttp.ClientError as err:
            raise DtekError(f"Getting info failed: {err}") from err
        except TimeoutError as err:
            raise DtekError("Getting info timed out.") from err

    async def _async_fetch_csrf(self) -> str:
        """Load the shutdowns page and return its CSRF token."""
        headers = {"User-Agent": USER_AGENT}
        async with self._session.get(self._base_url, headers=headers) as resp:
            resp.raise_for_status()
            html = await resp.text()
        match = _CSRF_META_RE.search(html)
        if not match:
            raise DtekError("CSRF token not found on the shutdowns page.")
        return match.group(1)

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
