"""
Module: modules.stakeholders.report_starters

The parts of the platform's starter report layouts (Business Requirements Document, Engineering Specification,
Review Package) that draw on Stakeholders, Personas and Stakeholder Needs.

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
    section,
    table,
    widget,
)

REPORT_STARTER_SECTIONS: tuple[ReportStarterSection, ...] = (
    ReportStarterSection(BRD, 30, section(
        "Stakeholders and Personas",
        "Who is affected and who the work is for.",
        table("stakeholder", [("code", "Code"), ("title", "Stakeholder"), ("role", "Role"), ("interests", "Interests")],
              empty="No stakeholders recorded."),
        table("persona", [("code", "Code"), ("title", "Persona"), ("role_title", "Role"), ("goals", "Goals")],
              empty="No Personas recorded."),
    )),
    ReportStarterSection(BRD, 40, section(
        "Stakeholder Needs",
        "What stakeholders need, before it becomes a requirement.",
        table("stakeholder_need", [("code", "Code"), ("title", "Need"), ("description", "Description"), ("status", "Status")],
              empty="No Stakeholder Needs recorded."),
    )),
    ReportStarterSection(BRD, 112, section(
        "Need coverage",
        "How many Stakeholder Needs are met by requirements.",
        widget("stakeholders.need-coverage.figures", "Need coverage is not available in this project."),
    )),
    ReportStarterSection(SPEC, 40, section(
        "Stakeholder and system needs",
        "The needs the requirements answer.",
        table("stakeholder_need", [("code", "Code"), ("title", "Need"), ("description", "Description"), ("status", "Status")],
              empty="No Stakeholder Needs recorded."),
    )),
    ReportStarterSection(SPEC, 82, section(
        "Need coverage",
        "How many Stakeholder Needs are met by requirements.",
        widget("stakeholders.need-coverage.figures", "Need coverage is not available in this project."),
    )),
)
