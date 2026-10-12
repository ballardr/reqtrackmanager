"""
Module: modules.risk_management.labels

Human-readable labels for Risk Management's enum wire values, for reports and
API consumers. Mirrors the frontend's label maps in
`frontend/src/modules/risk_management/types.ts` by hand (the same split the
other modules use). Lookups fall back to the raw value so a newly added member
renders rather than crashing.
"""

from __future__ import annotations

RISK_STATUS_LABEL: dict[str, str] = {
    "identified": "Identified",
    "assessed": "Assessed",
    "treatment_planned": "Treatment planned",
    "treatment_in_progress": "Treatment in progress",
    "mitigated": "Mitigated",
    "accepted": "Accepted",
    "transferred": "Transferred",
    "avoided": "Avoided",
    "realised": "Realised",
    "rejected": "Rejected",
    "closed": "Closed",
}

TREATMENT_STRATEGY_LABEL: dict[str, str] = {
    "mitigate": "Mitigate",
    "transfer": "Transfer",
    "avoid": "Avoid",
    "accept": "Accept",
}


def risk_status_label(value: str) -> str:
    """Returns the display label for a `RiskStatus` value (the raw value if unmapped)."""
    return RISK_STATUS_LABEL.get(value, value)
