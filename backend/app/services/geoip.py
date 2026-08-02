"""
Module: services.geoip

Optional best-effort IP-to-location lookup for login events (C-A-07).

Disabled by default (`GEOIP_LOOKUP_ENABLED=false`) since it calls a
third-party service with the client's IP address on every login — a real
external dependency and privacy trade-off, not something to do silently.
When enabled, private/internal address ranges are still never sent to the
external service (`GEOIP_LOOKUP_EXCLUDE_CIDRS`, defaulting to the standard
RFC1918/loopback ranges).

The lookup always runs as a FastAPI background task scheduled *after* the
login response has already been returned, and every failure mode (timeout,
network error, excluded address, disabled feature) resolves to doing
nothing — so login itself can never be slowed down or blocked by this
feature, regardless of the external service's availability.
"""

from __future__ import annotations

import ipaddress
import logging
from uuid import UUID

import httpx

from app.config import get_settings
from app.database import SessionLocal
from app.models.audit import LoginEvent

logger = logging.getLogger(__name__)

_GEOIP_URL = "http://ip-api.com/json/{ip}?fields=status,country,regionName,city"
_TIMEOUT_SECONDS = 3.0


def _is_excluded(ip_address: str) -> bool:
    """Returns True if `ip_address` is unparseable or falls within one of
    the configured excluded ranges (private/internal networks by default)."""
    try:
        addr = ipaddress.ip_address(ip_address)
    except ValueError:
        return True
    settings = get_settings()
    return any(addr in network for network in settings.geoip_lookup_exclude_networks)


def _resolve_location(ip_address: str) -> str | None:
    """Synchronously resolves an IP's approximate "city, region, country".

    Returns None on any failure, timeout, or excluded/unparseable address.
    This function is advisory-only and must never raise.
    """
    if _is_excluded(ip_address):
        return None
    try:
        response = httpx.get(_GEOIP_URL.format(ip=ip_address), timeout=_TIMEOUT_SECONDS)
        data = response.json()
        if data.get("status") != "success":
            return None
        parts = [p for p in (data.get("city"), data.get("regionName"), data.get("country")) if p]
        return ", ".join(parts) or None
    except Exception:
        logger.warning("GeoIP lookup failed for a login event's IP address.", exc_info=True)
        return None


def resolve_and_store_login_location(login_event_id: UUID, ip_address: str) -> None:
    """Background-task entry point scheduled from the login endpoint.

    Runs after the login response has already been sent, using its own
    database session (the request's session is closed by then). No-ops
    entirely if `GEOIP_LOOKUP_ENABLED` is false.

    Args:
        login_event_id: The `LoginEvent` row to attach the resolved
            location to.
        ip_address: The client IP address captured at login time.
    """
    if not get_settings().geoip_lookup_enabled:
        return
    location = _resolve_location(ip_address)
    if location is None:
        return
    db = SessionLocal()
    try:
        event = db.get(LoginEvent, login_event_id)
        if event is not None:
            event.location = location
            db.commit()
    finally:
        db.close()
