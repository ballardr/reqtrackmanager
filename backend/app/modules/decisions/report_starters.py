"""
Module: modules.decisions.report_starters

The parts of the platform's starter report layouts (Business Requirements Document, Engineering Specification,
Review Package) that draw on Decisions.

Responsibilities:
- Declare this module's `ReportStarterSection`s, which `ModuleDefinition.report_starter_sections` registers so the core
  starters (`services.report_starters`) name no module.

Design decisions:
- Each part is plain layout blocks over the report field registry and the widget catalogue. The core wraps a
  part in an `if` on this module, so a project where the module is off leaves it out.
- A part opens with its own heading; the core starters hold only the parts about core records.

Dependencies: `modules.registry` (`ReportStarterSection`), `services.report_starter_blocks`.
"""

from __future__ import annotations

from app.modules.registry import ReportStarterSection
from app.services.report_starter_blocks import (
    BUSINESS_REQUIREMENTS_DOCUMENT as BRD,
)
from app.services.report_starter_blocks import (
    ENGINEERING_SPECIFICATION as SPEC,
)
from app.services.report_starter_blocks import (
    REVIEW_PACKAGE as REVIEW,
)
from app.services.report_starter_blocks import (
    section,
    table,
    widget,
)

_ASSUMPTIONS_OR_CONSTRAINTS = [
    {"any": [{"field": "assumptions", "op": "not_empty"}, {"field": "constraints", "op": "not_empty"}]},
]

_CONSTRAINTS = section(
    "Constraints and assumptions",
    "Assumptions and constraints recorded on decisions.",
    table("decision", [("code", "Code"), ("title", "Decision"), ("assumptions", "Assumptions"), ("constraints", "Constraints")],
          empty="No assumptions or constraints recorded.", where=_ASSUMPTIONS_OR_CONSTRAINTS),
)

_DECISIONS = section(
    "Key decisions",
    "The decisions taken and why.",
    table("decision", [("code", "Code"), ("title", "Decision"), ("decision_statement", "Decision"), ("rationale", "Rationale"),
                       ("status", "Status")],
          empty="No decisions recorded."),
)

_COVERAGE = section(
    "Decision coverage",
    "How many decisions are tied to the requirements they affect.",
    widget("decisions.rationale-coverage.figures", "Decision coverage is not available in this project."),
)

REPORT_STARTER_SECTIONS: tuple[ReportStarterSection, ...] = (
    ReportStarterSection(BRD, 80, _CONSTRAINTS),
    ReportStarterSection(BRD, 90, _DECISIONS),
    ReportStarterSection(BRD, 113, _COVERAGE),
    ReportStarterSection(SPEC, 50, _CONSTRAINTS),
    ReportStarterSection(SPEC, 70, section(
        "Decisions affecting the specification",
        "The decisions taken and why.",
        _DECISIONS[2],
    )),
    ReportStarterSection(SPEC, 83, _COVERAGE),
    ReportStarterSection(REVIEW, 30, section(
        "Decisions awaiting approval",
        "Decisions waiting for their approver.",
        widget("decisions.approval-ageing.awaiting", "No decisions are awaiting approval."),
    )),
)
