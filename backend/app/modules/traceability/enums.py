"""
Module: modules.traceability.enums

Closed vocabularies of the module: how a governance profile binds a project, which projects it reaches, what it does for
one project, how a profile's stage workflow binds a project, and how a project's governance health is kept.

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


class StageWorkflowMode(str, Enum):
    """How a profile's stage workflow binds the projects it applies to.

    `DEFAULT` makes the workflow the one new stages start in, with the project still free to use others; `RESTRICT` also
    limits the project to the workflows its profiles name.
    """

    DEFAULT = "default"
    RESTRICT = "restrict"


#: The refresh cadences a project may choose for interval snapshots, in hours: hourly, a few times a day, then whole days
#: (2, 3, 5, 7, 10 and 14).
HEALTH_INTERVAL_HOURS: tuple[int, ...] = (1, 6, 12, 24, 48, 72, 120, 168, 240, 336)
#: The interval a project that chooses interval snapshots without naming one gets.
DEFAULT_HEALTH_INTERVAL_HOURS = 24


class HealthMode(str, Enum):
    """How a project's governance health is produced.

    `ON_DEMAND` computes it for each viewer when they open it; `SNAPSHOT_INTERVAL` serves a stored snapshot refreshed at a
    set interval; `SNAPSHOT_ON_CHANGE` serves a stored snapshot that is recomputed on the next read after the project's
    records change.
    """

    ON_DEMAND = "on_demand"
    SNAPSHOT_INTERVAL = "snapshot_interval"
    SNAPSHOT_ON_CHANGE = "snapshot_on_change"

    @property
    def is_snapshot(self) -> bool:
        """Whether a stored snapshot is served."""
        return self is not HealthMode.ON_DEMAND
