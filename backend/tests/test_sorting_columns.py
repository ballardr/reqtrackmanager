"""
Pins the column sorts of the requirements and change request lists that need more than the record's own columns: the
target stage, the level, the component and category, the places and the external references. Each sorts across every
page on the server (a paged list cannot sort only the rows it has loaded).
"""

from tests.conftest import auth_headers, create_component_and_category, create_project


def _names(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [row["name"] for row in response.json()]


def _stages(client, token, project_id) -> list[str]:
    """The project's stage ids in their order, with a second stage added when the project starts with one."""
    headers = auth_headers(token)
    stages = client.get(f"/api/v1/projects/{project_id}/stages", headers=headers).json()
    if len(stages) < 2:
        client.post(f"/api/v1/projects/{project_id}/stages", json={"name": "Second stage"}, headers=headers)
        stages = client.get(f"/api/v1/projects/{project_id}/stages", headers=headers).json()
    return [s["id"] for s in sorted(stages, key=lambda s: s["sort_order"])]


def test_requirements_sort_by_target_stage_then_level(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    first, second = _stages(client, admin_token, project["id"])[:2]
    headers = auth_headers(admin_token)
    for name, stage, level in [
        ("Late optional", second, "optional"), ("Early recommended", first, "recommended"),
        ("Late mandatory", second, "requirement"), ("Early mandatory", first, "requirement"),
    ]:
        created = client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"name": name, "component_id": component_id, "category_id": category_id, "target_stage_id": stage, "level": level},
            headers=headers,
        )
        assert created.status_code == 201, created.text

    base = f"/api/v1/projects/{project['id']}/requirements"
    expected = ["Early mandatory", "Early recommended", "Late mandatory", "Late optional"]
    assert _names(client.get(f"{base}?sort=target", headers=headers)) == expected
    assert _names(client.get(f"{base}?sort=target&order=desc", headers=headers)) == expected[::-1]
    # The page is cut after the order is applied, so a second page continues where the first stopped.
    assert _names(client.get(f"{base}?sort=target&limit=2&offset=2", headers=headers)) == expected[2:]


def test_requirements_sort_by_component_then_category_name(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    places = {}
    for component_name, prefix in [("Zulu hardware", "ZH"), ("Alpha software", "AS")]:
        component = client.post(
            f"/api/v1/projects/{project['id']}/components", json={"name": component_name, "prefix": prefix}, headers=headers,
        ).json()
        for category_name, category_prefix in [("Beta", "BE"), ("Alpha", "AL")]:
            category = client.post(
                f"/api/v1/projects/{project['id']}/categories",
                json={"name": category_name, "prefix": f"{prefix}{category_prefix}", "component_id": component["id"]}, headers=headers,
            ).json()
            places[(component_name, category_name)] = (component["id"], category["id"])
    for (component_name, category_name), (component_id, category_id) in places.items():
        client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"name": f"{component_name} / {category_name}", "component_id": component_id, "category_id": category_id}, headers=headers,
        )

    base = f"/api/v1/projects/{project['id']}/requirements"
    expected = ["Alpha software / Alpha", "Alpha software / Beta", "Zulu hardware / Alpha", "Zulu hardware / Beta"]
    assert _names(client.get(f"{base}?sort=placement", headers=headers)) == expected
    assert _names(client.get(f"{base}?sort=placement&order=desc", headers=headers)) == expected[::-1]


def test_requirements_sort_by_external_reference_with_none_last(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    headers = auth_headers(admin_token)
    system = client.post(f"/api/v1/projects/{project['id']}/external-systems", json={"name": "Tracker"}, headers=headers).json()
    ids = {}
    for name, key in [("Has ten", "PROJ-10"), ("Has two", "PROJ-2"), ("Has none", None)]:
        created = client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"name": name, "component_id": component_id, "category_id": category_id}, headers=headers,
        ).json()
        ids[name] = created["id"]
        if key:
            reference = client.post(
                f"/api/v1/projects/{project['id']}/artefacts/requirement/{created['id']}/external-references",
                json={"system_id": system["id"], "key": key}, headers=headers,
            )
            assert reference.status_code == 201, reference.text

    base = f"/api/v1/projects/{project['id']}/requirements"
    assert _names(client.get(f"{base}?sort=references", headers=headers)) == ["Has two", "Has ten", "Has none"]
    assert _names(client.get(f"{base}?sort=references&order=desc", headers=headers)) == ["Has none", "Has ten", "Has two"]
    assert _names(client.get(f"{base}?sort=references&limit=1&offset=1", headers=headers)) == ["Has ten"]


def test_change_requests_sort_by_target_level_and_references(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    first, second = _stages(client, admin_token, project["id"])[:2]
    system = client.post(f"/api/v1/projects/{project['id']}/external-systems", json={"name": "Tracker"}, headers=headers).json()
    made = {}
    for name, stage, level, key in [
        ("Late optional", second, "optional", "B-1"), ("Early mandatory", first, "requirement", "A-1"),
        ("Early recommended", first, "recommended", None),
    ]:
        created = client.post(
            f"/api/v1/projects/{project['id']}/change-requests",
            json={
                "kind": "new_requirement", "proposed_name": name, "reason": "because",
                "proposed_target_stage_id": stage, "proposed_level": level,
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        made[name] = created.json()["id"]
        if key:
            client.post(
                f"/api/v1/projects/{project['id']}/artefacts/change_request/{made[name]}/external-references",
                json={"system_id": system["id"], "key": key}, headers=headers,
            )

    def order(query: str) -> list[str]:
        response = client.get(f"/api/v1/projects/{project['id']}/change-requests?{query}", headers=headers)
        assert response.status_code == 200, response.text
        return [row["proposed_name"] for row in response.json()]

    assert order("sort=level") == ["Early mandatory", "Early recommended", "Late optional"]
    assert order("sort=level&order=desc") == ["Late optional", "Early recommended", "Early mandatory"]
    assert order("sort=target")[2] == "Late optional"
    assert order("sort=references") == ["Early mandatory", "Late optional", "Early recommended"]
    assert order("sort=places")  # accepted; no change request is placed, so the order is the stable tie order
