"""
Module: services.ui_preferences

Merges a partial update into a user's `ui_preferences` bag
(`User.ui_preferences`) while keeping the bag bounded
(docs/plans/platform-enhancements-2026-10-plan.md Phase 4).

Responsibilities:
- Shallow-merge a patch by top-level key; a `None` value removes the key, so a
  client can drop an override instead of storing a tombstone.
- Reject patches that would exceed the key-count, key-length or serialised-size
  limits, so an authenticated user cannot grow their own row without bound
  (the bag is returned on every `/auth/me`, so its size is paid on every login).

Design decisions:
- Limits are checked on the *merged* result, not just the patch, because many
  small patches can add up to an oversized bag.
- Values stay open-ended JSON (the bag's whole point is that a new preference
  is just a new key); only the overall size is bounded.

Dependencies: none (stdlib only).
"""

from __future__ import annotations

import json
from typing import Any

MAX_UI_PREFERENCE_KEYS = 200
MAX_UI_PREFERENCE_KEY_LENGTH = 100
MAX_UI_PREFERENCES_BYTES = 32 * 1024


def merge_ui_preferences(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """
    Returns `current` with `patch` shallow-merged in; `None` values delete their key.

    Args:
        current: The user's stored preference bag (not mutated).
        patch: Top-level keys to set or, with a `None` value, remove.

    Returns:
        A new dict to assign back to `User.ui_preferences` (reassignment, not in-place
        mutation, so SQLAlchemy change-tracking picks it up).

    Raises:
        ValueError: If a key is empty or too long, or the merged bag exceeds the key-count
            or serialised-size limit.
    """
    merged = dict(current)
    for key, value in patch.items():
        if not key or len(key) > MAX_UI_PREFERENCE_KEY_LENGTH:
            raise ValueError(f"UI preference keys must be 1-{MAX_UI_PREFERENCE_KEY_LENGTH} characters long.")
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    if len(merged) > MAX_UI_PREFERENCE_KEYS:
        raise ValueError(f"UI preferences are limited to {MAX_UI_PREFERENCE_KEYS} keys.")
    if len(json.dumps(merged, separators=(",", ":")).encode()) > MAX_UI_PREFERENCES_BYTES:
        raise ValueError(f"UI preferences are limited to {MAX_UI_PREFERENCES_BYTES // 1024} KiB in total.")
    return merged
