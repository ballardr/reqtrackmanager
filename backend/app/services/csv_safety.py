"""
Module: services.csv_safety

A single shared CSV formula/DDE injection guard (OWASP CSV injection),
used by every CSV-producing export in this codebase (report export,
requirement full-fidelity export) so the neutralization logic exists in
exactly one place rather than being re-derived per exporter.
"""

from __future__ import annotations

_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: str) -> str:
    """Neutralizes CSV formula/DDE injection (OWASP CSV injection).

    A cell starting with `=`, `+`, `-`, `@`, tab, or CR is interpreted as a
    formula by Excel/LibreOffice/Sheets when the file is opened — since
    these values often come straight from user-editable requirement fields
    and these exports exist specifically for spreadsheet consumption, a
    prefixed `'` (which spreadsheet apps strip from display but never
    execute) neutralizes it without altering how the value reads.
    """
    if value and value[0] in _FORMULA_TRIGGER_CHARS:
        return "'" + value
    return value
