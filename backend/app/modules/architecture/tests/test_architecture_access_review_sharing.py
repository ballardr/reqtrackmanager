"""The access review of what a project that is granted an element can read about it through the routes the core serves
(comments, tags, places, History, link graph, diagrams): the element itself, never what the owner's team wrote about it.
Every test builds its own organisation.
"""

from __future__ import annotations

import uuid

from app.modules.architecture.tests._helpers import (
    add_member,
    grant,
    make_architect,
    make_collection,
    make_diagram,
    make_element,
    place,
    project_base,
    setup,
)
from tests.conftest import auth_headers, create_project

_COMMENT = "OwnerOnlyComment"
_TAG = "owner-only-tag"


def _shared_world(client, admin_token):
    """An owner project with an element carrying a comment and a tag, a diagram showing it, and a consumer project it is granted
    to, with a plain member of the consumer only. Returns `(org, owner, consumer, element, token, member)`."""
    org, owner, token = setup(client, admin_token, f"Review share {uuid.uuid4().hex[:6]}")
    consumer = create_project(client, token, org["id"], "Consumer")
    element = make_element(client, token, owner["id"], "Shared thing", activate=True)
    own_diagram = make_diagram(client, token, owner["id"], "Owner diagram")
    place(client, token, owner["id"], own_diagram, element["id"], x=0, y=0)
    base = project_base(owner["id"])
    collection = make_collection(client, token, base, "Out", members=[element["id"]])
    grant(client, token, base, collection["id"], project_id=consumer["id"])
    posted = client.post(f"{base}/elements/{element['id']}/comments", json={"body": _COMMENT}, headers=auth_headers(token))
    assert posted.status_code == 201, posted.text
    tagged = client.put(
        f"/api/v1/projects/{owner['id']}/artefacts/architecture_element/{element['id']}/tags", json={"tags": [_TAG]},
        headers=auth_headers(token),
    )
    assert tagged.status_code in (200, 204), tagged.text
    _id, member = add_member(client, token, org["id"], consumer["id"], f"consumer.{uuid.uuid4().hex[:6]}@example.com")
    return org, owner, consumer, element, token, member


def test_a_project_granted_an_element_reads_none_of_what_the_owner_wrote_about_it(client, admin_token):
    _org, _owner, consumer, element, _token, member = _shared_world(client, admin_token)
    own_view = client.get(f"{project_base(consumer['id'])}/elements/{element['id']}", headers=auth_headers(member))
    assert own_view.status_code == 200 and own_view.json()["shared"] is True
    record = f"/api/v1/projects/{consumer['id']}/artefacts/architecture_element/{element['id']}"
    comment_route = f"{project_base(consumer['id'])}/elements/{element['id']}/comments"
    for url in (
        f"{record}/comments", f"{record}/anchored-comments", f"{record}/tags", f"{record}/placements", f"{record}/activity",
        f"{record}/link-graph", comment_route, f"{project_base(consumer['id'])}/elements/{element['id']}/diagrams",
        f"{project_base(consumer['id'])}/elements/{element['id']}/allocation",
    ):
        resp = client.get(url, headers=auth_headers(member))
        assert resp.status_code in (200, 403, 404), f"{url} -> {resp.status_code} {resp.text[:200]}"
        assert _COMMENT not in resp.text and _TAG not in resp.text and "Owner diagram" not in resp.text, f"{url}: {resp.text[:300]}"


def test_a_project_granted_an_element_cannot_change_what_the_owner_holds_about_it(client, admin_token):
    _org, owner, consumer, element, token, member = _shared_world(client, admin_token)
    architect = make_architect(client, token, _org["id"], consumer["id"], f"arch.{uuid.uuid4().hex[:6]}@example.com")
    record = f"/api/v1/projects/{consumer['id']}/artefacts/architecture_element/{element['id']}"
    for who in (member, architect):
        client.put(f"{record}/tags", json={"tags": ["intruder"]}, headers=auth_headers(who))
        client.post(f"{project_base(consumer['id'])}/elements/{element['id']}/comments", json={"body": "intruder comment"}, headers=auth_headers(who))
    owner_tags = client.get(
        f"/api/v1/projects/{owner['id']}/artefacts/architecture_element/{element['id']}/tags", headers=auth_headers(token),
    )
    owner_comments = client.get(f"{project_base(owner['id'])}/elements/{element['id']}/comments", headers=auth_headers(token))
    assert "intruder" not in owner_tags.text, owner_tags.text
    assert "intruder" not in owner_comments.text, owner_comments.text
