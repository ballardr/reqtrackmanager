"""
Module: modules.traceability.enums

Closed vocabularies of the module's governance profiles: how a profile binds a project, which projects it reaches
and what it does for one project.

Responsibilities:
- Name each value once; the model stores the value as a plain string and the services validate against these.

Design decisions:
- The three modes and two target kinds are fixed product concepts, not vocabularies a module extends, so they are enums.
- `ProfileOutcome` is the answer to "what does this profile do for this project", shared by the project view, the
  organisation's impact view and policy resolution, so the three can never disagree.

Dependencies: none.
"""

from __future__ import annotations

from enum import Enum


class ProfileMode(str, Enum):
    """How a profile reaches the projects it targets.

    `ENFORCED` binds every targeted project and only a named exemption lifts it; `DEFAULT` applies unless the project
    opts out; `OPT_IN` applies only where the project chooses it.
    """

    ENFORCED = "enforced"
    DEFAULT = "default"
    OPT_IN = "opt_in"


class ProfileTargetKind(str, Enum):
    """Which projects a profile reaches: every project of the organisation, or the listed projects (each optionally with
    its nested child projects, which also expresses "a project with its nested children")."""

    ALL_PROJECTS = "all_projects"
    SELECTED_PROJECTS = "selected_projects"


class ProfileOutcome(str, Enum):
    """What one profile does for one project.

    `ENFORCED`, `DEFAULT` and `OPTED_IN` mean the profile applies; the others mean it does not.
    """

    ENFORCED = "enforced"
    EXEMPT = "exempt"
    DEFAULT = "default"
    OPTED_OUT = "opted_out"
    OPTED_IN = "opted_in"
    AVAILABLE = "available"
    NOT_TARGETED = "not_targeted"

    @property
    def applies(self) -> bool:
        """Whether the profile's policy applies to the project."""
        return self in (ProfileOutcome.ENFORCED, ProfileOutcome.DEFAULT, ProfileOutcome.OPTED_IN)
