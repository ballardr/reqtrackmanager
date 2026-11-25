"""
Pins scripts/check_licences.py and scripts/generate_third_party_notices.py: the committed third-party inventory is
current and passes the licence policy, a dependency with a disallowed licence fails the guard, and the generator's
output is deterministic.

Skipped when the repository root is not visible (the backend container mounts only backend/); CI's `licences` job
and the pre-commit hook run the scripts directly.
"""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name):
    """Imports a script from scripts/ as a module; returns None if the repository checkout is not visible."""
    path = SCRIPTS / f"{name}.py"
    if not path.is_file():
        return None
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # the scripts import one another and use dataclasses, which look the module up by name
    spec.loader.exec_module(module)
    return module


inv = _load("licence_inventory")
checker = _load("check_licences")
generator = _load("generate_third_party_notices")
pytestmark = pytest.mark.skipif(inv is None, reason="repository checkout not available")


@pytest.fixture()
def policy():
    """The committed licence policy."""
    return inv.load_policy()


@pytest.fixture()
def inventory():
    """The committed third-party notices document."""
    return json.loads(inv.NOTICES_PATH.read_text(encoding="utf-8"))


def test_committed_inventory_passes_the_policy(policy, inventory):
    """Every shipped component, system package, base image and font is allowed and named."""
    assert inv.check_policy(policy, inventory) == []


def test_committed_inventory_matches_the_lockfiles(policy, inventory):
    """The npm lockfiles and the pinned Python requirements agree with the committed inventory."""
    assert inv.check_inventory_current(policy, inventory) == []


def test_committed_files_are_in_the_generators_canonical_form(inventory):
    """Re-serialising the committed files changes nothing, so a regeneration produces no spurious diff."""
    assert inv.NOTICES_PATH.read_text(encoding="utf-8") == generator.dump(inventory)
    texts = json.loads(inv.TEXTS_PATH.read_text(encoding="utf-8"))
    assert inv.TEXTS_PATH.read_text(encoding="utf-8") == generator.dump(texts)
    referenced = {t for p in inventory["packages"] for t in p["texts"]} | {t for f in inventory["fonts"] for t in f["texts"]}
    assert referenced <= set(texts)


@pytest.mark.parametrize(
    "expression",
    ["MIT", "Apache-2.0 OR BSD-3-Clause", "MIT AND ISC", "(MPL-2.0 OR Apache-2.0)", "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0"],
)
def test_permissive_expressions_pass(policy, expression):
    """Permissive licences, alone or combined, are accepted."""
    assert inv.judge_licence(policy, "npm:x", expression) in ("ok", "notice")


@pytest.mark.parametrize(
    "expression",
    ["GPL-3.0-only", "GPL-2.0-or-later", "AGPL-3.0-or-later", "SSPL-1.0", "BUSL-1.1", "UNKNOWN", "", "Proprietary", "MIT AND GPL-3.0-only"],
)
def test_disallowed_expressions_fail(policy, expression):
    """GPL, AGPL, source-available, unknown and unrecognised licences fail, including as one term of an AND."""
    assert inv.judge_licence(policy, "npm:x", expression) not in ("ok", "notice")


def test_or_passes_when_one_alternative_is_allowed(policy):
    """A dual licence is judged by its best alternative, the way the licensee may choose."""
    assert inv.judge_licence(policy, "npm:x", "GPL-3.0-only OR MIT") == "ok"
    assert inv.judge_licence(policy, "npm:x", "GPL-3.0-only OR AGPL-3.0-only") not in ("ok", "notice")


def test_file_level_copyleft_needs_its_notice(policy):
    """MPL passes but is flagged for its notice and source terms."""
    assert inv.judge_licence(policy, "python:certifi", "MPL-2.0") == "notice"


def test_library_copyleft_passes_only_for_a_named_package(policy):
    """LGPL is accepted for the two reviewed packages and fails for any other."""
    assert inv.judge_licence(policy, "python:svglib", "LGPL-3.0-or-later") == "notice"
    assert inv.judge_licence(policy, "python:psycopg2-binary", "LGPL-3.0-or-later WITH openvpn-openssl-exception") == "notice"
    assert inv.judge_licence(policy, "python:another", "LGPL-3.0-or-later") not in ("ok", "notice")


def test_a_gpl_exception_clause_does_not_make_gpl_acceptable(policy):
    """`WITH` narrows nothing for the purpose of the guard: GPL with an exception still fails for a dependency."""
    assert inv.judge_licence(policy, "python:x", "GPL-3.0-or-later WITH GCC-exception-3.1") not in ("ok", "notice")


def test_guard_fails_on_a_fixture_dependency_with_a_disallowed_licence(policy, inventory, monkeypatch, tmp_path, capsys):
    """The command-line guard exits 1 and names a package whose licence is GPL."""
    broken = copy.deepcopy(inventory)
    broken["packages"].append(
        {"ecosystem": "npm", "name": "fixture-gpl", "version": "1.0.0", "components": ["frontend"], "licence": "GPL-3.0-only", "texts": []}
    )
    path = tmp_path / "third-party-notices.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    monkeypatch.setattr(inv, "NOTICES_PATH", path)
    assert checker.main([]) == 1
    assert "npm:fixture-gpl@1.0.0" in capsys.readouterr().out


def test_guard_fails_on_an_unrecorded_system_package(policy, inventory, monkeypatch):
    """A Dockerfile that installs an operating-system package the policy does not name fails."""
    real = inv.dockerfile_system_packages()
    first = next(iter(real))
    monkeypatch.setattr(inv, "dockerfile_system_packages", lambda: {**real, first: real[first] | {"fixture-package"}})
    problems = inv.check_policy(policy, inventory)
    assert any("fixture-package" in p for p in problems)


def test_guard_fails_on_an_unrecorded_base_image(policy, inventory, monkeypatch):
    """A Dockerfile that builds from an image the policy does not name fails."""
    monkeypatch.setattr(inv, "dockerfile_base_images", lambda: {"fixture/image:1"} | set(policy["base_images"]))
    assert any("fixture/image:1" in p for p in inv.check_policy(policy, inventory))


def test_system_copyleft_is_allowed_only_for_a_separate_program_or_build_tool():
    """Ghostscript-style AGPL is fine as a separate program and rejected as a linked library."""
    component = {"name": "x", "licence": "AGPL-3.0-or-later", "use": "separate-program", "reason": "Separate process."}
    assert inv.judge_system_component(component) == "ok"
    assert inv.judge_system_component({**component, "use": "library"}) != "ok"
    assert inv.judge_system_component({**component, "reason": ""}) != "ok"
    assert inv.judge_system_component({"name": "y", "licence": "BSD-2-Clause", "use": "library"}) == "ok"


def test_dockerfile_package_parser_handles_continuations_operators_and_comments():
    """Options, comments, later install commands in the same RUN and non-install commands are read correctly."""
    text = (
        "# apt-get install commentedpackage\n"
        "RUN apt-get update && apt-get install -y --no-install-recommends \\\n"
        "    curl zlib1g \\\n"
        "    && rm -rf /var/lib/apt/lists/* \\\n"
        "    && apt-get install -y gnupg && apt-get purge -y gnupg\n"
        "RUN apk add --no-cache wget\n"
    )
    assert inv.parse_dockerfile_packages(text) == {"curl", "zlib1g", "gnupg", "wget"}


def test_every_override_and_named_exception_states_its_evidence(policy):
    """An exception to metadata-derived licences records why, so it can be reviewed later."""
    assert all(o["licence"] and len(o["evidence"]) > 20 for o in policy["overrides"].values())
    assert set(policy["library_copyleft_named"]) == set(policy["library_copyleft_reasons"])


def test_python_licence_resolution_order(policy):
    """A declared expression wins, then a short licence field, then a single classifier; ambiguity is UNKNOWN; an override wins over all."""
    base = {"name": "fixture-pkg", "expression": None, "licence": None, "classifiers": []}
    assert inv.resolve_python_licence({**base, "expression": "MIT OR Apache-2.0"}, policy) == ("MIT OR Apache-2.0", "metadata")
    assert inv.resolve_python_licence({**base, "licence": "Apache License, Version 2.0"}, policy) == ("Apache-2.0", "metadata")
    assert inv.resolve_python_licence({**base, "classifiers": ["License :: OSI Approved :: MIT License"]}, policy) == ("MIT", "classifier")
    assert inv.resolve_python_licence({**base, "classifiers": ["License :: OSI Approved :: BSD License"]}, policy)[0] == "UNKNOWN"
    assert inv.resolve_python_licence({**base, "licence": "UNKNOWN"}, policy)[0] == "UNKNOWN"
    assert inv.resolve_python_licence({**base, "name": "qrcode", "expression": "GPL-3.0-only"}, policy) == ("BSD-3-Clause", "override")


def test_generator_output_is_deterministic(policy):
    """Collecting the same lockfile twice and serialising gives identical bytes; identical texts share one id."""
    first = [(p.name, p.version, p.licence) for p in inv.collect_npm("frontend", policy)]
    second = [(p.name, p.version, p.licence) for p in inv.collect_npm("frontend", policy)]
    assert first == second == sorted(first)
    texts: dict[str, str] = {}
    assert generator.add_text(texts, "Licence A\r\n") == generator.add_text(texts, "Licence A\n\n")
    assert len(texts) == 1
    assert generator.dump({"b": 1, "a": [2]}) == generator.dump({"a": [2], "b": 1})


def test_development_only_npm_packages_are_excluded(policy):
    """The frontend inventory holds production packages only (the lockfile marks tooling `dev`)."""
    lock = json.loads((inv.ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    dev_only = {inv.npm_package_name(k) for k, v in lock["packages"].items() if k and v.get("dev")}
    prod = {inv.npm_package_name(k) for k, v in lock["packages"].items() if k and not v.get("dev")}
    included = {p.name for p in inv.collect_npm("frontend", policy)}
    assert included == prod
    assert not (included & (dev_only - prod))
