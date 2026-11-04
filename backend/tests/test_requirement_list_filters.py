"""Requirement list filters that bound what a table download carries: component and a target stage range.

The list, its Export and its Download report all read the same filters, so the requirement report's old
filter section (R-G-03) is reached from the list page instead. These tests pin the component filter and the
stage range (by the stages' order, never their names), including through the shared export route.
"""
import csv
import io

from tests.conftest import auth_headers, create_component_and_category, create_project


def _project_with_requirements(client, admin_token, org_id):
    """A project with stages S0 < S1 < S2 and one requirement per stage plus one with the first stage, in a second component."""
    project = create_project(client, admin_token, org_id)
    pid = project["id"]
    headers = auth_headers(admin_token)
    component_id, category_id = create_component_and_category(client, admin_token, pid)
    other_component = client.post(
        f"/api/v1/projects/{pid}/components", json={"name": "Hardware", "prefix": "HW"}, headers=headers,
    ).json()["id"]
    other_category = client.post(
        f"/api/v1/projects/{pid}/categories", json={"name": "Thermal", "prefix": "THM", "component_id": other_component},
        headers=headers,
    ).json()["id"]
    for name in ("S1", "S2"):
        assert client.post(f"/api/v1/projects/{pid}/stages", json={"name": name}, headers=headers).status_code == 201
    stages = client.get(f"/api/v1/projects/{pid}/stages", headers=headers).json()
    stages.sort(key=lambda s: s["sort_order"])
    assert len(stages) == 3
    made: dict[str, str] = {}
    for index, stage in enumerate(stages):
        resp = client.post(
            f"/api/v1/projects/{pid}/requirements",
            json={"name": f"At stage {index}", "component_id": component_id, "category_id": category_id,
                  "target_stage_id": stage["id"]},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        made[f"stage{index}"] = resp.json()["id"]
    resp = client.post(
        f"/api/v1/projects/{pid}/requirements",
        json={"name": "Hardware at stage 0", "component_id": other_component, "category_id": other_category,
              "target_stage_id": stages[0]["id"]},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return pid, stages, component_id, other_component, made


def _names(client, admin_token, pid, query: str) -> list[str]:
    resp = client.get(f"/api/v1/projects/{pid}/requirements?{query}", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    return sorted(r["name"] for r in resp.json())


def test_component_filter_keeps_only_that_components_requirements(client, admin_token, org_id):
    pid, _stages, component_id, other_component, _made = _project_with_requirements(client, admin_token, org_id)

    assert _names(client, admin_token, pid, f"component_id={other_component}") == ["Hardware at stage 0"]
    assert len(_names(client, admin_token, pid, f"component_id={component_id}")) == 3


def test_stage_range_is_inclusive_and_follows_stage_order(client, admin_token, org_id):
    pid, stages, *_ = _project_with_requirements(client, admin_token, org_id)
    first, middle, last = (s["id"] for s in stages)

    assert _names(client, admin_token, pid, f"target_stage_from_id={middle}&target_stage_to_id={last}") == [
        "At stage 1", "At stage 2",
    ]
    assert _names(client, admin_token, pid, f"target_stage_from_id={first}&target_stage_to_id={middle}") == [
        "At stage 0", "At stage 1", "Hardware at stage 0",
    ]
    # A range of one stage is that stage; an open end reaches the first or last stage.
    assert _names(client, admin_token, pid, f"target_stage_from_id={middle}&target_stage_to_id={middle}") == ["At stage 1"]
    assert _names(client, admin_token, pid, f"target_stage_from_id={last}") == ["At stage 2"]
    assert _names(client, admin_token, pid, f"target_stage_to_id={first}") == ["At stage 0", "Hardware at stage 0"]


def test_stage_range_ignores_stage_names(client, admin_token, org_id):
    """Renaming stages so their names sort the other way round does not change which are 'later'."""
    pid, stages, *_ = _project_with_requirements(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    for stage, name in zip(stages, ("Zulu", "Mike", "Alpha"), strict=True):
        assert client.patch(f"/api/v1/projects/{pid}/stages/{stage['id']}", json={"name": name}, headers=headers).status_code == 200

    assert _names(client, admin_token, pid, f"target_stage_from_id={stages[1]['id']}") == ["At stage 1", "At stage 2"]


def test_a_range_that_is_backwards_or_names_a_foreign_stage_matches_nothing(client, admin_token, org_id):
    pid, stages, *_ = _project_with_requirements(client, admin_token, org_id)
    other = create_project(client, admin_token, org_id, "Other")
    foreign = client.get(f"/api/v1/projects/{other['id']}/stages", headers=auth_headers(admin_token)).json()[0]["id"]

    assert _names(client, admin_token, pid, f"target_stage_from_id={stages[2]['id']}&target_stage_to_id={stages[0]['id']}") == []
    assert _names(client, admin_token, pid, f"target_stage_from_id={foreign}") == []


def test_single_stage_filter_still_works(client, admin_token, org_id):
    pid, stages, *_ = _project_with_requirements(client, admin_token, org_id)

    assert _names(client, admin_token, pid, f"target_stage_id={stages[1]['id']}") == ["At stage 1"]


def test_export_carries_the_component_and_stage_range(client, admin_token, org_id):
    """The list's Export (and so Download report) narrows by the same filters as the list."""
    pid, stages, _component_id, other_component, _made = _project_with_requirements(client, admin_token, org_id)
    headers = auth_headers(admin_token)

    def exported(query: str) -> list[str]:
        resp = client.get(f"/api/v1/projects/{pid}/records/requirement/export?{query}", headers=headers)
        assert resp.status_code == 200, resp.text
        return sorted(row["name"] for row in csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))

    assert exported(f"component_id={other_component}") == ["Hardware at stage 0"]
    assert exported(f"target_stage_from_id={stages[1]['id']}&target_stage_to_id={stages[2]['id']}") == [
        "At stage 1", "At stage 2",
    ]
