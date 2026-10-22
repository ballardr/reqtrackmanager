"""Pins that the Stakeholders module builds its composite routers once.

Combining the sub-routers re-creates every route's validation model (about three
seconds for the project router), and the report catalogue asks for the router on
every request, so an uncached getter made every Reports page load wait that long.
"""

from __future__ import annotations

import time

from app.modules.stakeholders.module import get_project_router, get_router


def test_composite_routers_are_built_once() -> None:
    """Repeated calls return the same router object, not a rebuilt one."""
    assert get_router() is get_router()
    assert get_project_router() is get_project_router()


def test_project_router_lookup_is_fast_once_built() -> None:
    """A lookup after the first build is far below the cost of a rebuild."""
    get_project_router()
    started = time.perf_counter()
    for _ in range(20):
        get_project_router()
    assert time.perf_counter() - started < 0.5
