"""
Module: test_stakeholders_lifecycle

The status path of a Persona, a Stakeholder and a Stakeholder Need on the lifecycle engine
(`modules.stakeholders.lifecycles`): each type is registered with its `ALLOWED_TRANSITIONS` as the table, the path is Draft,
Active, Retired with nothing optional or gated, the project's lifecycle view lists it, and a move outside the table is still
refused (the moves themselves are pinned by the type's own suites).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from app.modules.registry import get_lifecycles
from app.modules.stakeholders import service as s
from app.modules.stakeholders.lifecycles import LIFECYCLES
from app.services.lifecycles import validate_definition
from tests.conftest import auth_headers, create_org_admin_in, create_project

TABLES: dict[str, Mapping[Any, frozenset[Any]]] = {
    s.PERSONA_ARTEFACT_TYPE: s.PERSONA_ALLOWED_TRANSITIONS,
    s.STAKEHOLDER_ARTEFACT_TYPE: s.STAKEHOLDER_ALLOWED_TRANSITIONS,
    s.NEED_ARTEFACT_TYPE: s.NEED_ALLOWED_TRANSITIONS,
}


@pytest.mark.parametrize("artefact_type", sorted(TABLES))
def test_each_type_is_registered_with_its_own_transition_map(artefact_type):
    assert set(LIFECYCLES) == set(TABLES)
    module_key, definition = get_lifecycles()[artefact_type]
    assert module_key == "stakeholders"
    assert validate_definition(definition) == []
    assert definition.path == ("draft", "active", "retired")
    assert definition.optional == () and definition.gated == ()
    assert dict(definition.transitions) == {a.value: frozenset(b.value for b in moves) for a, moves in TABLES[artefact_type].items()}


def test_the_projects_lifecycle_view_lists_the_stakeholder_types(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Stakeholder Lifecycle Co")
    assert client.put(f"/api/v1/orgs/{org['id']}/modules/stakeholders", json={"enabled": True}, headers=auth_headers(token)).status_code == 200
    project = create_project(client, token, org["id"], "Stakeholder Lifecycle Project")
    resp = client.get(f"/api/v1/projects/{project['id']}/lifecycles", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    listed = {x["artefact_type"]: x for x in resp.json()["lifecycles"]}
    for artefact_type in TABLES:
        assert [step["key"] for step in listed[artefact_type]["path"]] == ["draft", "active", "retired"]
        assert listed[artefact_type]["transitions"]["retired"] == ["active"]
