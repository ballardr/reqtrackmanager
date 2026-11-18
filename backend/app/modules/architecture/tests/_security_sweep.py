"""Sweep helpers for the Architecture module's access review: the module's real route table, the path of each route filled from
a world's records, one request with the smallest valid body, and the schema-driven example behind it.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from typing import Any

from fastapi.routing import APIRoute

from tests.conftest import auth_headers

MODULE = "/modules/architecture"
WRITES = {"POST", "PUT", "PATCH", "DELETE"}
#: Routes any project member may call by design (a comment needs only the right to read the record).
MEMBER_WRITES = re.compile(r"/(elements|connections|diagrams|state-machine-diagrams)/\{record_id\}/comments$")
_UUID = "00000000-0000-4000-8000-000000000001"


def routes(app) -> Iterator[tuple[str, str, APIRoute]]:
    """Every `(method, path, route)` of the module (the project and organisation routers, and baseline creation)."""
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if MODULE not in route.path and not route.path.endswith("/baselines"):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            yield method, route.path, route


def segment_kind(path: str) -> str:
    """What a `{record_id}`, `{diagram_id}`, `{folder_id}` or `{type_id}` path names, from the path's words."""
    for word in ("state-machine-diagrams", "element-folders", "connection-folders", "diagram-folders", "element-types",
                 "connection-types", "domains", "symbols", "elements", "connections", "diagrams"):
        if f"/{word}" in path:
            return word
    return ""


def fill(path: str, owner: dict[str, str], ids: dict[str, str]) -> str:
    """The path with every parameter replaced by the record the world holds for it (a random id when it holds none).

    Args:
        path: A route path with `{name}` parameters.
        owner: `project_id` and `organization_id` to use.
        ids: The records, keyed `element`, `connection`, `diagram`, `machine`, `state`, `transition`, `port`, `collection`,
            `grant`, `baseline`, `item`, `folder_element`, `folder_connection`, `folder_diagram`, `element_type`,
            `connection_type`, `domain` and `symbol`.
    """
    kind = segment_kind(path)
    by_name = {
        "record_id": {"elements": "element", "connections": "connection", "diagrams": "diagram",
                      "state-machine-diagrams": "machine"}.get(kind, "element"),
        "diagram_id": "machine" if "state-machine-diagrams" in path else "diagram",
        "folder_id": {"element-folders": "folder_element", "connection-folders": "folder_connection",
                      "diagram-folders": "folder_diagram"}.get(kind, "folder_element"),
        "type_id": {"element-types": "element_type", "connection-types": "connection_type", "domains": "domain",
                    "symbols": "symbol"}.get(kind, "element_type"),
        "baseline_id": "baseline", "item_id": "item", "collection_id": "collection", "grant_id": "grant",
        "element_id": "element", "connection_id": "connection", "state_id": "state", "transition_id": "transition",
        "port_id": "port", "symbol_id": "symbol",
    }

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in owner:
            return owner[name]
        return ids.get(by_name.get(name, ""), str(uuid.uuid4()))

    return re.sub(r"\{(\w+)\}", replace, path)


def call(client, method: str, url: str, token: str, body: Any = None, route: APIRoute | None = None):
    """One request. A symbol upload is multipart; a route's required query parameters (a record's `version`) are given so the
    request reaches the route's own checks instead of failing validation."""
    kwargs: dict[str, Any] = {"headers": auth_headers(token)}
    if route is not None:
        required = {p.alias: "1" for p in route.dependant.query_params if p.field_info.is_required()}
        if required:
            kwargs["params"] = required
    if method == "POST" and url.endswith("/symbols"):
        kwargs["files"] = {"file": ("symbol.svg", b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>', "image/svg+xml")}
    elif method in {"POST", "PUT", "PATCH"}:
        kwargs["json"] = body if body is not None else {}
    return client.request(method, url, **kwargs)


def minimal_body(route: APIRoute) -> Any:
    """The smallest body the route's schema accepts, so a request reaches the route's own checks instead of failing validation."""
    field = route.body_field
    if field is None:
        return None
    model: Any = field.field_info.annotation
    schema = model.model_json_schema() if hasattr(model, "model_json_schema") else {}
    return _example(schema, schema.get("$defs", {}))


def _example(schema: dict, defs: dict) -> Any:
    """A minimal valid JSON value for a JSON schema (required object fields only)."""
    if "$ref" in schema:
        return _example(defs[schema["$ref"].rsplit("/", 1)[-1]], defs)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [o for o in schema[key] if o.get("type") != "null"]
            return _example(options[0], defs) if options else None
    if "allOf" in schema:
        return _example(schema["allOf"][0], defs)
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        return {name: _example(schema["properties"][name], defs) for name in schema.get("required", [])}
    if kind == "array":
        return [_example(schema.get("items", {}), defs) for _ in range(schema.get("minItems", 0))]
    if kind in ("integer", "number"):
        return max(schema.get("minimum", 1), 1)
    if kind == "boolean":
        return False
    if schema.get("format") == "uuid":
        return _UUID
    if kind == "string":
        return "x" * max(schema.get("minLength", 1), 1)
    return None
