"""
Module: modules.architecture.baseline_compare

Compares two sets of architecture records: a baseline against the live model, or one baseline against another.

Responsibilities:
- `compare`: for each record type, the records only in the second set (added), only in the first (removed), those in both
  whose content differs (changed, field by field) and how many are identical.

Design decisions (all Decided by: Agent):
- **One shape, two sources.** Both sides are `{type: [content]}` in the snapshot shape (`baseline_snapshot`), so a live
  comparison reads the model through the same code that wrote the baseline, and a difference can never come from the two
  being built differently.
- **Records match by code.** A record's `unique_code` identifies it within its project and is stable for its life. A
  baseline restored from a project bundle holds the codes the source project had, so it compares against its own origin only.
- **Fields.** A scalar field reports its before and after as text. A list field (ports, boxes, states, tags) is compared as a
  set of entries, reporting the entries added and removed; a change of order alone is not a change.
- **Display text only.** A value is rendered as text here (a nested object as compact JSON) so the screen needs no knowledge
  of each field's shape; the field's own name is the key, labelled by the frontend.

Dependencies: none beyond the standard library (the callers read the records).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as default_field
from typing import Any

#: Keys that identify a record and are never reported as a change.
_IDENTITY_KEYS = frozenset({"unique_code"})


@dataclass(frozen=True)
class RecordRef:
    """A record named in a comparison: its code, name and status (empty when the type has none)."""

    code: str
    name: str
    status: str | None


@dataclass(frozen=True)
class FieldChange:
    """One field that differs.

    Attributes:
        field: The content key (`description`, `ports`, `status`).
        before: The first side's value as text; `None` when it was empty, and for a list field.
        after: The second side's value as text; `None` when it is empty, and for a list field.
        added: For a list field, the entries only the second side holds, each as compact JSON.
        removed: For a list field, the entries only the first side holds.
    """

    field: str
    before: str | None
    after: str | None
    added: list[str] = default_field(default_factory=list)
    removed: list[str] = default_field(default_factory=list)


@dataclass(frozen=True)
class RecordChange:
    """A record present on both sides whose content differs."""

    record: RecordRef
    fields: list[FieldChange]


@dataclass(frozen=True)
class TypeComparison:
    """The comparison of one record type; `added` is in the second side only, `removed` in the first only."""

    item_type: str
    added: list[RecordRef]
    removed: list[RecordRef]
    changed: list[RecordChange]
    unchanged: int


def _text(value: Any) -> str | None:
    """A value as display text: `None` and an empty string are `None`, a nested object is compact JSON."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical(value: Any) -> str:
    """A stable text for a list entry, so equal entries match whatever their key order."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_ref(content: Mapping[str, Any]) -> RecordRef:
    """The reference line of a record: its code, its name (the code when it has none) and its status."""
    code = str(content.get("unique_code") or "")
    return RecordRef(code=code, name=str(content.get("name") or code), status=_text(content.get("status")))


def changed_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[FieldChange]:
    """The fields that differ between two contents of the same record, in the order they first appear.

    Args:
        before: The first side's content.
        after: The second side's content.

    Returns:
        One `FieldChange` per field whose value differs; a list field whose entries are the same set (in any order) is not
        a change. A key only one side holds counts as empty on the other.
    """
    changes: list[FieldChange] = []
    for key in dict.fromkeys([*before, *after]):
        if key in _IDENTITY_KEYS:
            continue
        old, new = before.get(key), after.get(key)
        if isinstance(old, list) or isinstance(new, list):
            old_entries, new_entries = Counter(map(_canonical, old or [])), Counter(map(_canonical, new or []))
            added, removed = new_entries - old_entries, old_entries - new_entries
            if added or removed:
                changes.append(FieldChange(field=key, before=None, after=None, added=sorted(added.elements()), removed=sorted(removed.elements())))
        elif _text(old) != _text(new):
            changes.append(FieldChange(field=key, before=_text(old), after=_text(new)))
    return changes


def compare(
    first: Mapping[str, Sequence[Mapping[str, Any]]], second: Mapping[str, Sequence[Mapping[str, Any]]],
    item_types: Sequence[str],
) -> list[TypeComparison]:
    """Compares the records of two sources, type by type.

    Args:
        first: `{type: [content]}` of the base side (the older baseline).
        second: `{type: [content]}` of the other side (a later baseline, or the live model).
        item_types: The types to compare, in the order to return them.

    Returns:
        One `TypeComparison` per type, with each list ordered by code.
    """
    result: list[TypeComparison] = []
    for item_type in item_types:
        old = {str(c.get("unique_code")): c for c in first.get(item_type, ())}
        new = {str(c.get("unique_code")): c for c in second.get(item_type, ())}
        changed: list[RecordChange] = []
        unchanged = 0
        for code in sorted(old.keys() & new.keys()):
            fields = changed_fields(old[code], new[code])
            if fields:
                changed.append(RecordChange(record=record_ref(new[code]), fields=fields))
            else:
                unchanged += 1
        result.append(TypeComparison(
            item_type=item_type,
            added=[record_ref(new[code]) for code in sorted(new.keys() - old.keys())],
            removed=[record_ref(old[code]) for code in sorted(old.keys() - new.keys())],
            changed=changed, unchanged=unchanged,
        ))
    return result
