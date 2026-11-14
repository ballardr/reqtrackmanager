"""
Module: modules.architecture.report_starters

The parts of the platform's starter report layouts that draw on the project's architecture.

Responsibilities:
- Declare this module's `ReportStarterSection`s, which `ModuleDefinition.report_starter_sections` registers so the core
  starters (`services.report_starters`) name no module.

Design decisions (Decided by: Agent):
- **Engineering Specification: the system architecture.** The element tree and the interface list, as widgets over the
  reports AR4 and AR3, so the starter and the Reports page show the same rows. Diagram drawings are not in a starter:
  they need a diagram chosen, which the person does when they add the Diagram widget (AR5).
- **Review Package: the allocation gaps,** from AR2, because a review asks what is not yet covered.
- Each part opens with its own heading; the core wraps it in an `if` on this module, so a project where the module is
  off leaves it out.

Dependencies: `modules.registry` (`ReportStarterSection`), `services.report_starter_blocks`.
"""

from __future__ import annotations

from app.modules.architecture.service import ARCHITECTURE_MODULE_KEY
from app.modules.registry import ReportStarterSection
from app.services.report_starter_blocks import (
    ENGINEERING_SPECIFICATION as SPEC,
)
from app.services.report_starter_blocks import (
    REVIEW_PACKAGE as REVIEW,
)
from app.services.report_starter_blocks import (
    section,
    widget,
)

REPORT_STARTER_SECTIONS: tuple[ReportStarterSection, ...] = (
    ReportStarterSection(SPEC, 70, section(
        "System architecture",
        "The project's elements by parent, and the connections between them.",
        widget(f"{ARCHITECTURE_MODULE_KEY}.element-breakdown.tree", "No elements recorded."),
        widget(f"{ARCHITECTURE_MODULE_KEY}.interface-list.connections", "No connections recorded."),
    )),
    ReportStarterSection(REVIEW, 70, section(
        "Architecture allocation",
        "Requirements with no allocated element, and elements with no requirement.",
        widget(f"{ARCHITECTURE_MODULE_KEY}.allocation-coverage.requirements", "Every requirement is allocated."),
        widget(f"{ARCHITECTURE_MODULE_KEY}.allocation-coverage.elements", "Every element has a requirement."),
    )),
)
