"""
Module: modules.context_strategy.report_starters

The parts of the platform's starter report layouts (Business Requirements Document, Engineering Specification,
Review Package) that draw on Pain Points, Strategies, Future States, Guiding Principles and Open Questions.

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

REPORT_STARTER_SECTIONS: tuple[ReportStarterSection, ...] = (
    ReportStarterSection(BRD, 20, section(
        "Business problems and Pain Points",
        "The problems the work addresses, from the project's Pain Points.",
        table("pain_point", [("code", "Code"), ("title", "Pain Point"), ("priority", "Priority"), ("status", "Status"), ("impact", "Impact")],
              empty="No Pain Points recorded."),
    )),
    ReportStarterSection(BRD, 50, section(
        "Business objectives and Strategy",
        "The objectives the work serves and how success is measured.",
        table("strategy", [("code", "Code"), ("title", "Strategy"), ("objective", "Objective"),
                           ("measures_of_success", "Measures of success"), ("status", "Status")],
              empty="No Strategies recorded."),
    )),
    ReportStarterSection(BRD, 60, section(
        "Future State",
        "Where the organisation intends to be.",
        table("future_state", [("code", "Code"), ("title", "Future State"), ("desired_state", "Desired state"),
                               ("success_measures", "Success measures"), ("target_date", "Target date")],
              empty="No Future States recorded."),
    )),
    ReportStarterSection(BRD, 111, section(
        "Pain Point coverage",
        "How many Pain Points are addressed by requirements.",
        widget("context_strategy.pain-point-coverage.figures", "Pain Point coverage is not available in this project."),
    )),
    ReportStarterSection(BRD, 120, section(
        "Open Questions",
        "What is still undecided.",
        table("open_question", [("code", "Code"), ("title", "Question"), ("priority", "Priority"), ("owner", "Owner"),
                                ("due_date", "Due"), ("status", "Status")],
              empty="No Open Questions recorded."),
    )),
    ReportStarterSection(SPEC, 11, section(
        "Guiding principles",
        "The principles that guide the specification.",
        table("guiding_principle", [("code", "Code"), ("title", "Principle"), ("principle_statement", "Statement"), ("status", "Status")],
              empty="No Guiding Principles recorded."),
    )),
    ReportStarterSection(SPEC, 81, section(
        "Pain Point coverage",
        "How many Pain Points are addressed by requirements.",
        widget("context_strategy.pain-point-coverage.figures", "Pain Point coverage is not available in this project."),
    )),
    ReportStarterSection(REVIEW, 40, section(
        "Open Questions",
        "Questions still open, and those past their due date.",
        widget("context_strategy.open-question-register.open", "No Open Questions."),
        widget("context_strategy.open-question-register.overdue", "No Open Questions are overdue."),
    )),
)
