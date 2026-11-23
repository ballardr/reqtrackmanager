"""
Module: modules.risk_management.report_starters

The parts of the starter report layouts (Business Requirements Document,
Engineering Specification, Review Package) that draw on Risks, registered through
`ModuleDefinition.report_starter_sections` so core names no module. Each part is
plain layout blocks opening with its own heading; the core wraps it in an `if`.
"""

from __future__ import annotations

from app.modules.registry import ReportStarterSection
from app.services.report_starter_blocks import (
    BUSINESS_REQUIREMENTS_DOCUMENT as BRD,
)
from app.services.report_starter_blocks import (
    REVIEW_PACKAGE as REVIEW,
)
from app.services.report_starter_blocks import (
    section,
    table,
    widget,
)

REPORT_STARTER_SECTIONS: tuple[ReportStarterSection, ...] = (
    ReportStarterSection(BRD, 100, section(
        "Risks and business impacts",
        "What could go wrong and the consequence for the business.",
        table("risk", [("code", "Code"), ("title", "Risk"), ("consequence", "Consequence"), ("treatment_strategy", "Treatment"),
                       ("status", "Status")],
              empty="No risks recorded."),
    )),
    ReportStarterSection(REVIEW, 50, section(
        "Risk reviews",
        "Risks whose review is overdue, and those whose treatment needs reassessing.",
        widget("risk_management.review-schedule.overdue", "No risk reviews are overdue."),
        widget("risk_management.treatment-coverage.needs_reassessment", "No risks need reassessing."),
    )),
)
