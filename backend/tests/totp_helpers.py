"""A controllable clock for the application's TOTP check, and a code generator that moves it on.

Kept out of `conftest.py` on purpose: the conftest module can be loaded under two names, and state held there would
then exist twice (the fixture would move one clock while a test read the other).
"""

from __future__ import annotations

import pyotp


class TotpClock:
    """The time the application's TOTP check reads in tests: each `next_code` call moves it on one time step, so a
    test can use several codes in a row without the replay rule (a code is accepted once) refusing the second."""

    now = 0.0


def next_code(secret: str) -> str:
    """A valid TOTP code for `secret` one time step after the previous `next_code` of the test."""
    TotpClock.now += 30
    return pyotp.TOTP(secret).at(int(TotpClock.now))
