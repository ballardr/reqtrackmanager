"""Tests that keep the browser's copy of the diagram resolver in step with `diagram_resolver.resolve`.

The editor redraws lines in the browser with a TypeScript port of the resolver. Both are run over the same scenarios,
whose inputs and expected results live in `frontend/src/modules/architecture/diagramResolverCases.json`: the Python
resolver produces the expected results here, and the port's story test checks that it returns the same. This test
fails when the file is out of date with the resolver, so a change to the rule cannot reach one side only.

To refresh the file after a deliberate change to the rule, run this test with `UPDATE_RESOLVER_CASES=1`, then review the
diff and update the port.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from app.modules.architecture.diagram_resolver import MAX_HOPS, ModelConnection, resolve

CASES_FILE = (
    Path(__file__).resolve().parents[5] / "frontend" / "src" / "modules" / "architecture" / "diagramResolverCases.json"
)


def _id(kind: str, name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"{kind}-{name}")


def _scenario(
    name: str, *, parents: dict[str, str | None], placed: list[str], connections: list[tuple], hidden: tuple[str, ...] = (),
    hidden_connections: tuple[str, ...] = (), merge_parallel: bool = False,
) -> dict:
    """One case: inputs by name (turned into ids) and the resolver's answer.

    `connections` are `(name, source, target)` or `(name, source, target, "two-way")`."""
    elements = {n: _id("element", n) for n in parents}
    model = [
        ModelConnection(_id("connection", c[0]), elements[c[1]], elements[c[2]], not (len(c) > 3 and c[3] == "two-way"))
        for c in connections
    ]
    result = resolve(
        placed=[elements[n] for n in placed],
        parents={elements[n]: (elements[p] if p else None) for n, p in parents.items()},
        connections=model, hidden_elements=[elements[n] for n in hidden],
        hidden_connections=[_id("connection", n) for n in hidden_connections], merge_parallel=merge_parallel,
    )
    return {
        "name": name,
        "labels": {str(i): n for n, i in elements.items()} | {str(_id("connection", c[0])): c[0] for c in connections},
        "placed": [str(elements[n]) for n in placed],
        "parents": {str(elements[n]): (str(elements[p]) if p else None) for n, p in parents.items()},
        "connections": [
            {"id": str(m.id), "source_id": str(m.source_id), "target_id": str(m.target_id), "directional": m.directional}
            for m in model
        ],
        "hidden_elements": [str(elements[n]) for n in hidden],
        "hidden_connections": [str(_id("connection", n)) for n in hidden_connections],
        "merge_parallel": merge_parallel,
        "expected": {
            "hidden_placed": sorted(str(i) for i in result.hidden_placed),
            "internal": {str(k): [str(i) for i in v] for k, v in sorted(result.internal.items(), key=lambda kv: str(kv[0]))},
            "lines": [
                {
                    "source_id": str(ln.source_id), "target_id": str(ln.target_id), "two_way": ln.two_way,
                    "connection_ids": [str(i) for i in ln.connection_ids], "rolled_up": ln.rolled_up,
                    "bridged": ln.bridged, "indirect": ln.indirect, "hops": [str(i) for i in ln.hops],
                }
                for ln in result.lines
            ],
        },
    }


def _flat(*names: str) -> dict[str, str | None]:
    return {n: None for n in names}


def _chain_of_hidden() -> dict:
    """A run of hidden elements longer than the hop limit, so the walk's cap is part of the contract."""
    hidden = [f"h{i}" for i in range(MAX_HOPS + 2)]
    names = ["a", *hidden, "b"]
    return _scenario(
        "a chain of hidden elements longer than the hop limit joins nothing",
        parents=_flat(*names), placed=["a", "b"], hidden=tuple(hidden),
        connections=[(f"c{i}", names[i], names[i + 1]) for i in range(len(names) - 1)],
    )


def cases() -> list[dict]:
    """Every scenario with the resolver's answer."""
    return [
        _scenario("a direct connection is one solid line", parents=_flat("a", "b"), placed=["a", "b"], connections=[("ab", "a", "b")]),
        _scenario(
            "a two-way connection is a two-way line", parents=_flat("a", "b"), placed=["a", "b"],
            connections=[("ab", "a", "b", "two-way")],
        ),
        _scenario(
            "an end rolls up to its nearest placed ancestor",
            parents={"p": None, "child": "p", "grandchild": "child", "x": None}, placed=["p", "x"],
            connections=[("gx", "grandchild", "x")],
        ),
        _scenario(
            "a nearer placed ancestor wins over a farther one",
            parents={"p": None, "child": "p", "grandchild": "child", "x": None}, placed=["p", "child", "x"],
            connections=[("gx", "grandchild", "x")],
        ),
        _scenario(
            "an end under no placed element is not drawn", parents=_flat("a", "b", "c"), placed=["a", "b"],
            connections=[("ac", "a", "c")],
        ),
        _scenario(
            "a connection inside one placed element is internal", parents={"p": None, "x": "p", "y": "p", "z": None},
            placed=["p", "z"], connections=[("xy", "x", "y"), ("xz", "x", "z")],
        ),
        _scenario(
            "several connections rolled up to one pair share a dashed line",
            parents={"p": None, "x": "p", "y": "p", "z": None}, placed=["p", "z"],
            connections=[("xz", "x", "z"), ("yz", "y", "z")],
        ),
        _scenario(
            "parallel direct lines stay apart with detail", parents=_flat("a", "b"), placed=["a", "b"],
            connections=[("one", "a", "b"), ("two", "a", "b")],
        ),
        _scenario(
            "parallel direct lines merge without detail", parents=_flat("a", "b"), placed=["a", "b"],
            connections=[("one", "a", "b"), ("two", "b", "a")], merge_parallel=True,
        ),
        _scenario(
            "a merged line with a direct member stays solid", parents={"p": None, "x": "p", "z": None},
            placed=["p", "z"], connections=[("rolled", "x", "z"), ("direct", "p", "z")], merge_parallel=True,
        ),
        _scenario(
            "a hidden transit element is bridged and its hop listed", parents=_flat("a", "mid", "b"), placed=["a", "b"],
            hidden=("mid",), connections=[("in", "a", "mid"), ("out", "mid", "b")],
        ),
        _scenario(
            "a placed transit element that is on draws the real connections", parents=_flat("a", "mid", "b"),
            placed=["a", "mid", "b"], connections=[("in", "a", "mid"), ("out", "mid", "b")],
        ),
        _scenario(
            "a chain of hidden elements lists every hop in order", parents=_flat("a", "h1", "h2", "b"),
            placed=["a", "b"], hidden=("h1", "h2"),
            connections=[("c1", "a", "h1"), ("c2", "h1", "h2"), ("c3", "h2", "b")],
        ),
        _chain_of_hidden(),
        _scenario(
            "a hidden dead end just disappears", parents=_flat("a", "dead"), placed=["a"], hidden=("dead",),
            connections=[("ad", "a", "dead")],
        ),
        _scenario(
            "bridging follows the direction of the connections", parents=_flat("a", "mid", "b"), placed=["a", "b"],
            hidden=("mid",), connections=[("in", "b", "mid"), ("out", "mid", "a")],
        ),
        _scenario(
            "bridging against the direction draws nothing", parents=_flat("a", "mid", "b"), placed=["a", "b"],
            hidden=("mid",), connections=[("in", "mid", "a"), ("out", "mid", "b")],
        ),
        _scenario(
            "two-way connections bridge once as a two-way line", parents=_flat("a", "mid", "b"), placed=["a", "b"],
            hidden=("mid",), connections=[("in", "a", "mid", "two-way"), ("out", "mid", "b", "two-way")],
        ),
        _scenario(
            "a hidden element hides its subtree", parents={"top": None, "sub": "top", "a": None}, placed=["top", "sub", "a"],
            hidden=("top",), connections=[("sa", "sub", "a")],
        ),
        _scenario(
            "a hidden connection is left out and does not bridge", parents=_flat("a", "mid", "b"), placed=["a", "b"],
            hidden=("mid",), hidden_connections=("out",), connections=[("in", "a", "mid"), ("out", "mid", "b")],
        ),
        _scenario(
            "a bridged line that lands inside one placed element is internal",
            parents={"p": None, "x": "p", "y": "p", "mid": None}, placed=["p"], hidden=("mid",),
            connections=[("in", "x", "mid"), ("out", "mid", "y")],
        ),
        _scenario(
            "a parent cycle ends the walk", parents={"a": "b", "b": "a", "z": None}, placed=["a", "z"],
            connections=[("bz", "b", "z")],
        ),
        _scenario(
            "a connection to an unplaced element under a hidden placed one is hidden with it",
            parents={"top": None, "sub": "top", "z": None}, placed=["top", "z"], hidden=("top",),
            connections=[("sz", "sub", "z")],
        ),
    ]


def test_the_shared_resolver_cases_are_current():
    produced = json.dumps(cases(), indent=2, sort_keys=False) + "\n"
    if os.environ.get("UPDATE_RESOLVER_CASES") == "1":
        CASES_FILE.write_text(produced, encoding="utf-8")
    assert CASES_FILE.read_text(encoding="utf-8") == produced, (
        "diagramResolverCases.json is out of date with diagram_resolver.resolve; run this test with "
        "UPDATE_RESOLVER_CASES=1, review the diff and update the browser port to match."
    )


def test_the_cases_reach_every_resolver_behaviour():
    lines = [ln for case in cases() for ln in case["expected"]["lines"]]
    assert any(ln["bridged"] for ln in lines) and any(ln["rolled_up"] for ln in lines)
    assert any(ln["two_way"] for ln in lines) and any(not ln["indirect"] for ln in lines)
    assert any(len(ln["connection_ids"]) > 1 for ln in lines) and any(len(ln["hops"]) > 1 for ln in lines)
    assert any(case["expected"]["internal"] for case in cases())
    assert any(case["expected"]["hidden_placed"] for case in cases())
    assert any(case["merge_parallel"] for case in cases())
