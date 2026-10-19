"""Tests for the module's single "People" nav entry (Personas, Stakeholders, Needs and Groups on one page).

The entry must stay while any of the three sub-components is on and the wire shape must say so
(`nav_sub_components_any`), because the nav rail hides an entry only when all of them are off.
"""

from __future__ import annotations

from app.modules.stakeholders.tests.test_persona_api import _setup
from tests.conftest import auth_headers

MODULE_KEY = "stakeholders"
ANY = ["persona", "stakeholder", "stakeholder_need"]


def _entry(client, token, project_id) -> dict:
    resp = client.get(f"/api/v1/projects/{project_id}/enabled-modules", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return next(m for m in resp.json() if m["module_key"] == MODULE_KEY)


def test_people_is_the_primary_nav_entry_and_lists_the_sub_components_it_serves(client, admin_token):
    _, project, token = _setup(client, admin_token, "People Nav Co")
    entry = _entry(client, token, project["id"])
    manifest = entry["frontend_manifest"]

    assert manifest["nav_label"] == "People"
    assert manifest["nav_path"] == f"/projects/{project['id']}/modules/{MODULE_KEY}/people"
    assert manifest["nav_sub_component"] is None
    assert manifest["nav_sub_components_any"] == ANY
    # Personas, Stakeholders, Needs and Groups are no longer separate nav entries.
    assert [e["nav_label"] for e in manifest["additional_nav_entries"]] == ["Engagements"]
    # Only the off-by-default research extras are disabled; none of the sub-components People serves is.
    assert not set(ANY) & set(entry["disabled_sub_components"])


def test_disabling_sub_components_is_reported_so_the_rail_can_hide_people_only_when_all_are_off(client, admin_token):
    _, project, token = _setup(client, admin_token, "People Nav Toggle Co")
    h = auth_headers(token)
    base = f"/api/v1/projects/{project['id']}/modules/{MODULE_KEY}/subcomponents"

    for key in ANY:
        assert client.put(f"{base}/{key}", json={"enabled": False}, headers=h).status_code == 200
        disabled = _entry(client, token, project["id"])["disabled_sub_components"]
        assert key in disabled

    entry = _entry(client, token, project["id"])
    assert set(ANY) <= set(entry["disabled_sub_components"])
    assert entry["frontend_manifest"]["nav_sub_components_any"] == ANY
