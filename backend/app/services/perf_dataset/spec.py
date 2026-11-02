"""
Module: services.perf_dataset.spec

Turns a profiles document (`perf/datasets/profiles.yaml`) plus a tier, a breadth profile, a link density and a
seed into a `DatasetSpec`: the recorded, immutable description of what one generated dataset contains.

Responsibilities:
- Validate the profiles document and the names a caller picked, so a typo fails before anything is written.
- Hold the ratios that scale every record type, and the topology (organisations, projects, nesting).
- Derive a stable identity (`DatasetSpec.snapshot_key`) so a snapshot made for one spec is never reused for another.

Design decisions:
- The numbers live in the profiles file, not in code, so they are a versioned input of each run rather than a
  constant buried in a generator. This module only validates and structures them.
- A spec is frozen and hashable; every random choice downstream comes from a `random.Random` seeded from it, so
  the same spec produces the same dataset on every host.

Dependencies: standard library only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

#: Bumped when the generator's output shape changes, so snapshots made by an older generator are not reused.
GENERATOR_VERSION = 2


class ProfileError(ValueError):
    """The profiles document or a requested name is invalid; the message names the problem."""


@dataclass(frozen=True)
class Ratios:
    """Records of other types per requirement, and the shape of the links between requirements.

    Attributes:
        actions: Actions per requirement.
        comments: Review comments per requirement (mean).
        tags_per_requirement: Tags attached per requirement (mean).
        versions_per_requirement: Versions per requirement (mean, at least 1).
        tag_vocabulary: Tags defined in each project.
        mean_degree: Mean links touching one requirement.
        hub_exponent: Zipf exponent of the link endpoint weights (higher means hubbier).
        cross_level_link_fraction: Share of a nested project's links that join it to its parent.
        dormant_link_fraction: Share of a nested project's cross-type links that join it to a sibling project (not in
            its ancestry), which the application treats as dormant (counted unavailable, never shown).
        hub_max_degree: Links planted on the most-linked record of each type (capped by the records available to
            link from), so every project has a real hub; 0 plants none.
        compliance: The profiles' `compliance` section as pairs: `standards_per_org`, `requirements_per_standard`,
            `required_action_fraction` and `standards_per_project`. Empty when the profiles omit it (no compliance data).
        records: `(artefact type, records per requirement)` for every other registered type, from `ratios.records` in
            the profiles (a tuple of pairs, so the spec stays hashable). A type absent here is not generated.
    """

    actions: float
    comments: float
    tags_per_requirement: float
    versions_per_requirement: float
    tag_vocabulary: int
    mean_degree: float
    hub_exponent: float
    cross_level_link_fraction: float
    dormant_link_fraction: float = 0.0
    hub_max_degree: int = 0
    records: tuple[tuple[str, float], ...] = ()
    compliance: tuple[tuple[str, float], ...] = ()

    def compliance_setting(self, name: str) -> float:
        """A value of the profiles' `compliance` section (the catalogue size and what a project takes from it)."""
        return dict(self.compliance)[name]

    def per_requirement(self, artefact_type: str) -> float:
        """Records of `artefact_type` per requirement (0 when the profiles do not name the type)."""
        return dict(self.records).get(artefact_type, 0.0)

    def count_for(self, artefact_type: str, requirements: int) -> int:
        """How many records of `artefact_type` a project of `requirements` requirements holds (at least one for a
        non-zero ratio, so a small tier still exercises every type)."""
        ratio = self.per_requirement(artefact_type)
        return 0 if ratio <= 0 else max(1, round(requirements * ratio))


@dataclass(frozen=True)
class Topology:
    """How many organisations and projects the dataset has, and how projects nest.

    Attributes:
        organisations: Organisations created.
        projects_per_org: Projects in each organisation when not nested.
        nesting_depth: Levels of a project tree (1 means no nesting); 0 when the profile is not nested.
        nesting_fanout: Children of every project above the last level.
    """

    organisations: int
    projects_per_org: int
    nesting_depth: int = 0
    nesting_fanout: int = 0

    @property
    def is_nested(self) -> bool:
        """Whether projects form a tree."""
        return self.nesting_depth > 0

    @property
    def projects_in_org(self) -> int:
        """Projects each organisation holds."""
        if not self.is_nested:
            return self.projects_per_org
        return sum(self.nesting_fanout**level for level in range(self.nesting_depth))


@dataclass(frozen=True)
class DatasetSpec:
    """Everything that decides what a generated dataset contains.

    Attributes:
        tier: Tier name (`T0`..`T4`).
        requirements_per_project: Requirements in each project.
        breadth: Breadth profile name.
        density: Link density name (`sparse`, `typical`, `dense`).
        seed: Seed for every random choice.
        profiles_version: The profiles document's `version`.
        ratios: Per-requirement ratios.
        topology: Organisations and projects.
        users_per_org: People created in each organisation.
    """

    tier: str
    requirements_per_project: int
    breadth: str
    density: str
    seed: int
    profiles_version: int
    ratios: Ratios
    topology: Topology
    users_per_org: int = 6
    extra: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @property
    def total_projects(self) -> int:
        """Projects across every organisation."""
        return self.topology.organisations * self.topology.projects_in_org

    @property
    def total_requirements(self) -> int:
        """Requirements across every project."""
        return self.total_projects * self.requirements_per_project

    def snapshot_key(self, schema_revision: str) -> str:
        """A short stable name for the snapshot of this spec on this schema.

        Args:
            schema_revision: The database's migration head, so a snapshot of an older schema is not reused.

        Returns:
            A filename-safe key such as `T2-single-typical-s1-3fa9c1d2e0b4`.
        """
        payload = json.dumps(
            {
                "tier": self.tier,
                "n": self.requirements_per_project,
                "breadth": self.breadth,
                "density": self.density,
                "seed": self.seed,
                "profiles": self.profiles_version,
                "ratios": self.ratios.__dict__,
                "topology": self.topology.__dict__,
                "users": self.users_per_org,
                "generator": GENERATOR_VERSION,
                "schema": schema_revision,
            },
            sort_keys=True,
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()[:12]
        return f"{self.tier}-{self.breadth}-{self.density}-s{self.seed}-{digest}"

    def describe(self) -> dict[str, Any]:
        """The spec as plain data, for the dataset manifest."""
        return {
            "tier": self.tier,
            "requirements_per_project": self.requirements_per_project,
            "breadth": self.breadth,
            "density": self.density,
            "seed": self.seed,
            "profiles_version": self.profiles_version,
            "generator_version": GENERATOR_VERSION,
            "ratios": dict(self.ratios.__dict__),
            "topology": dict(self.topology.__dict__),
            "users_per_org": self.users_per_org,
            "total_projects": self.total_projects,
            "total_requirements": self.total_requirements,
        }


def _number(profiles: dict, path: str, value: Any, *, minimum: float = 0) -> float:
    """Returns `value` if it is a number at least `minimum`, else raises `ProfileError` naming `path`."""
    if isinstance(value, bool) or not isinstance(value, int | float) or value < minimum:
        raise ProfileError(f"profiles: {path} must be a number >= {minimum}, got {value!r}")
    return value


def build_spec(profiles: dict, *, tier: str, breadth: str = "single", density: str = "typical", seed: int = 1) -> DatasetSpec:
    """Validates a profiles document and builds the spec for one choice of tier, breadth, density and seed.

    Args:
        profiles: The parsed `profiles.yaml`.
        tier: A key of `profiles["tiers"]`.
        breadth: A key of `profiles["breadth"]`.
        density: A key of `profiles["link_density"]`.
        seed: The random seed (any integer).

    Returns:
        The frozen spec.

    Raises:
        ProfileError: If the document is malformed or a name is not defined in it.
    """
    for section in ("version", "tiers", "ratios", "link_density", "breadth"):
        if section not in profiles:
            raise ProfileError(f"profiles: missing section {section!r}")
    tiers, ratios, densities, breadths = profiles["tiers"], profiles["ratios"], profiles["link_density"], profiles["breadth"]
    if tier not in tiers:
        raise ProfileError(f"unknown tier {tier!r}; defined: {', '.join(sorted(tiers))}")
    if density not in densities:
        raise ProfileError(f"unknown link density {density!r}; defined: {', '.join(sorted(densities))}")
    if breadth not in breadths:
        raise ProfileError(f"unknown breadth profile {breadth!r}; defined: {', '.join(sorted(breadths))}")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ProfileError("seed must be an integer")

    shape = breadths[breadth]
    organisations = int(_number(profiles, f"breadth.{breadth}.organisations", shape.get("organisations"), minimum=1))
    nesting = shape.get("nesting")
    if nesting:
        topology = Topology(
            organisations=organisations,
            projects_per_org=0,
            nesting_depth=int(_number(profiles, f"breadth.{breadth}.nesting.depth", nesting.get("depth"), minimum=2)),
            nesting_fanout=int(_number(profiles, f"breadth.{breadth}.nesting.fanout", nesting.get("fanout"), minimum=1)),
        )
    else:
        topology = Topology(
            organisations=organisations,
            projects_per_org=int(_number(profiles, f"breadth.{breadth}.projects_per_org", shape.get("projects_per_org"), minimum=1)),
        )

    built = Ratios(
        actions=_number(profiles, "ratios.actions", ratios.get("actions")),
        comments=_number(profiles, "ratios.comments", ratios.get("comments")),
        tags_per_requirement=_number(profiles, "ratios.tags_per_requirement", ratios.get("tags_per_requirement")),
        versions_per_requirement=_number(profiles, "ratios.versions_per_requirement", ratios.get("versions_per_requirement"), minimum=1),
        tag_vocabulary=int(_number(profiles, "ratios.tag_vocabulary", ratios.get("tag_vocabulary"), minimum=1)),
        mean_degree=_number(profiles, f"link_density.{density}.mean_degree", densities[density].get("mean_degree")),
        hub_exponent=_number(profiles, "hub_exponent", profiles.get("hub_exponent"), minimum=0.1),
        cross_level_link_fraction=_number(profiles, "cross_level_link_fraction", profiles.get("cross_level_link_fraction", 0)),
        dormant_link_fraction=_number(profiles, "dormant_link_fraction", profiles.get("dormant_link_fraction", 0)),
        hub_max_degree=int(_number(profiles, "hub_max_degree", profiles.get("hub_max_degree", 0))),
        records=tuple(
            (name, float(_number(profiles, f"ratios.records.{name}", value)))
            for name, value in sorted((ratios.get("records") or {}).items())
        ),
        compliance=tuple(
            (name, float(_number(profiles, f"compliance.{name}", value)))
            for name, value in sorted((profiles.get("compliance") or {}).items())
        ),
    )
    return DatasetSpec(
        tier=tier,
        requirements_per_project=int(_number(profiles, f"tiers.{tier}", tiers[tier], minimum=1)),
        breadth=breadth,
        density=density,
        seed=seed,
        profiles_version=int(profiles["version"]),
        ratios=built,
        topology=topology,
        users_per_org=int(_number(profiles, "users_per_org", profiles.get("users_per_org", 6), minimum=2)),
    )
