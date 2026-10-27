"""
Module: modules.compliance.report_starters

The parts of the platform's starter report layouts (Business Requirements Document, Engineering Specification,
Review Package) that draw on the project's adopted compliance requirements.

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
    ENGINEERING_SPECIFICATION as SPEC,
)
from app.services.report_starter_blocks import (
    section,
    table,
)

REPORT_STARTER_SECTIONS: tuple[ReportStarterSection, ...] = (
    ReportStarterSection(SPEC, 60, section(
        "Applicable compliance obligations",
        "The compliance requirements this project has adopted.",
        table("project_compliance_requirement", [("code", "Code"), ("title", "Obligation"), ("status", "Status"),
                                                 ("justification", "Justification")],
              empty="No compliance obligations adopted."),
    )),
)
