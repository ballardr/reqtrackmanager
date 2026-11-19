#!/usr/bin/env python3
"""
Module: licence_inventory

Collects the licence of every third-party component this product ships and judges it against the licence policy
(`scripts/licence_policy.json`).

Responsibilities:
- Read the npm lockfiles (frontend, documentation site) and resolve each Python requirements file (backend,
  mcp-server) in a throwaway virtual environment, so the Python inventory is the same closure an image build installs.
- Normalise each component's licence to an SPDX expression (declared expression, then the licence field, then the
  trove classifier, then a named override in the policy that records the evidence).
- Judge an SPDX expression against the policy: permissive and file-level copyleft licences pass, library copyleft
  (LGPL) passes only for a named package, and GPL, AGPL, SSPL, source-available and unknown licences fail.
- Cross-check the Dockerfiles: every operating-system package a Dockerfile installs is named in the policy.

Design decisions: development-only npm packages are excluded (they are not part of any image). Every Python package
in a requirements file is included because the image installs the whole file. The Python closure is resolved
with the running interpreter, so a transitive version may differ from an image built later; the policy check gates
licences, never versions. Standard library only; installing packages needs network access.

Used by: scripts/generate_third_party_notices.py, scripts/check_licences.py and backend/tests/test_licence_guard.py.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "scripts" / "licence_policy.json"

# A component is one image or site whose files carry the third-party code.
PYTHON_COMPONENTS = {
    "backend": "backend/requirements.txt",
    "mcp-server": "mcp-server/requirements.txt",
}
NPM_COMPONENTS = {
    "frontend": "frontend",
    "docs": "docs/website",
}
# Installed by the image tooling, never part of the application's own requirements.
IGNORED_PYTHON_DISTRIBUTIONS = {"pip", "setuptools", "wheel"}

# Python's licence metadata is free text; these are the spellings seen in practice, matched case-insensitively.
LICENCE_TEXT_ALIASES = {
    "mit": "MIT",
    "mit license": "MIT",
    "the mit license": "MIT",
    "mit-0": "MIT-0",
    "isc": "ISC",
    "isc license": "ISC",
    "isc license (iscl)": "ISC",
    "bsd-2-clause": "BSD-2-Clause",
    "bsd-3-clause": "BSD-3-Clause",
    "bsd 3-clause": "BSD-3-Clause",
    "apache-2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "apache software license": "Apache-2.0",
    "psf-2.0": "PSF-2.0",
    "psfl": "PSF-2.0",
    "unlicense": "Unlicense",
    "mpl-2.0": "MPL-2.0",
    "0bsd": "0BSD",
    "lgpl-3.0-or-later": "LGPL-3.0-or-later",
}
CLASSIFIER_ALIASES = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: BSD License": None,  # which BSD clause count is not stated
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: The Unlicense (Unlicense)": "Unlicense",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
}

# Collector run inside the throwaway environment; prints one JSON array of every installed distribution.
_COLLECTOR = r"""
import importlib.metadata as m, json, re
out = []
for d in m.distributions():
    md = d.metadata
    name = md["Name"]
    files = []
    root = d.locate_file("").resolve()

    def inside(path):
        # True when the path stays within the installation directory (a hostile License-File must not read elsewhere).
        try:
            return path.resolve().is_relative_to(root)
        except OSError:
            return False

    for f in md.get_all("License-File") or []:
        for cand in [d.locate_file(f)] + [c.locate() for c in (d.files or []) if str(c).replace("\\", "/").endswith("/" + f)][:1]:
            if cand.is_file() and inside(cand):
                files.append([f, cand.read_text(encoding="utf-8", errors="replace")])
                break
    if not files:
        for cand in (d.files or []):
            base = str(cand).replace("\\", "/").split("/")[-1].lower()
            if re.match(r"(licen[cs]e|copying|notice|unlicense)", base) and "dist-info" in str(cand) and inside(cand.locate()):
                files.append([cand.name, cand.locate().read_text(encoding="utf-8", errors="replace")])
    out.append({
        "name": name,
        "version": d.version,
        "expression": md.get("License-Expression"),
        "licence": md.get("License"),
        "classifiers": [c for c in (md.get_all("Classifier") or []) if c.startswith("License ::")],
        "files": files,
    })
print(json.dumps(out))
"""


@dataclass
class Package:
    """One third-party package with the licence evidence found for it."""

    ecosystem: str
    name: str
    version: str
    components: set[str] = field(default_factory=set)
    direct: bool = False
    licence: str = "UNKNOWN"
    licence_source: str = "none"
    files: list[list[str]] = field(default_factory=list)  # [file name, text] pairs of the licence files found

    @property
    def key(self) -> str:
        """Returns `ecosystem:name`, the form the policy names a package in."""
        return f"{self.ecosystem}:{self.name}"


def load_policy() -> dict:
    """Returns the parsed licence policy.

    Raises:
        FileNotFoundError: If the policy file is missing.
    """
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def normalise_python_name(name: str) -> str:
    """Returns a PEP 503 normalised distribution name (lower case, runs of `-_.` collapsed to `-`)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _tokenise(expression: str) -> list[str]:
    """Splits an SPDX expression into identifiers, `AND`, `OR`, `WITH` and parentheses."""
    return re.findall(r"\(|\)|[^\s()]+", expression)


class _Judge:
    """Recursive-descent judge of an SPDX expression against the policy."""

    def __init__(self, policy: dict, package_key: str):
        self.permissive = {i.lower() for i in policy["permissive"]}
        self.file_level = {i.lower() for i in policy["file_level_copyleft"]}
        self.library = {i.lower() for i in policy["library_copyleft"]}
        self.named = policy["library_copyleft_named"].get(package_key, [])
        self.denied_prefixes = tuple(p.lower() for p in policy["denied_prefixes"])

    def judge_id(self, identifier: str) -> str:
        """Returns `ok`, `notice` (file-level copyleft), or a failure reason for one SPDX identifier."""
        low = identifier.lower().rstrip("+")
        if low in self.permissive:
            return "ok"
        if low in self.file_level:
            return "notice"
        if low in self.library:
            return "notice" if identifier in self.named else f"{identifier} is library copyleft and the package is not named in the policy"
        if low.startswith(self.denied_prefixes):
            return f"{identifier} is a disallowed licence"
        return f"{identifier} is not in the policy"

    def parse(self, tokens: list[str]) -> str:
        """Evaluates a whole expression; OR passes when any alternative passes, AND needs every term to pass."""
        result, rest = self._or(tokens)
        if rest:
            return f"unparsed licence expression remainder: {' '.join(rest)}"
        return result

    def _or(self, tokens: list[str]) -> tuple[str, list[str]]:
        left, rest = self._and(tokens)
        results = [left]
        while rest and rest[0].upper() == "OR":
            right, rest = self._and(rest[1:])
            results.append(right)
        passing = [r for r in results if r in ("ok", "notice")]
        if passing:
            return ("ok" if "ok" in passing else "notice"), rest
        return results[0], rest

    def _and(self, tokens: list[str]) -> tuple[str, list[str]]:
        left, rest = self._atom(tokens)
        results = [left]
        while rest and rest[0].upper() == "AND":
            right, rest = self._atom(rest[1:])
            results.append(right)
        failing = [r for r in results if r not in ("ok", "notice")]
        if failing:
            return failing[0], rest
        return ("notice" if "notice" in results else "ok"), rest

    def _atom(self, tokens: list[str]) -> tuple[str, list[str]]:
        if not tokens:
            return "empty licence expression", []
        if tokens[0] == "(":
            result, rest = self._or(tokens[1:])
            if rest and rest[0] == ")":
                rest = rest[1:]
            return result, rest
        identifier, rest = tokens[0], tokens[1:]
        if rest and rest[0].upper() == "WITH":
            rest = rest[2:]
        return self.judge_id(identifier), rest


def judge_licence(policy: dict, package_key: str, expression: str) -> str:
    """Judges one licence expression for one package.

    Args:
        policy: The parsed licence policy.
        package_key: `ecosystem:name`, used to look up a named library-copyleft exception.
        expression: An SPDX licence expression.

    Returns:
        `ok`, `notice` (file-level copyleft: needs its notice and source terms) or a sentence naming why it fails.
    """
    if expression.strip().upper() in {"", "UNKNOWN", "NONE"}:
        return "the licence is unknown"
    return _Judge(policy, package_key).parse(_tokenise(expression))


def resolve_python_licence(raw: dict, policy: dict) -> tuple[str, str]:
    """Normalises a Python distribution's metadata to an SPDX expression.

    Args:
        raw: One entry from the collector (`expression`, `licence`, `classifiers`).
        policy: The parsed licence policy, whose `overrides` win over metadata.

    Returns:
        `(expression, source)`; the expression is `UNKNOWN` when nothing identifies the licence.
    """
    key = f"python:{normalise_python_name(raw['name'])}"
    override = policy["overrides"].get(key)
    if override:
        return override["licence"], "override"
    if raw.get("expression"):
        return raw["expression"].strip(), "metadata"
    text = (raw.get("licence") or "").strip()
    if text and len(text) < 80 and "\n" not in text:
        mapped = LICENCE_TEXT_ALIASES.get(text.lower())
        if mapped:
            return mapped, "metadata"
    classes = [CLASSIFIER_ALIASES.get(c, "?") for c in raw.get("classifiers", [])]
    if len(classes) == 1 and classes[0] not in (None, "?"):
        return classes[0], "classifier"
    return "UNKNOWN", "none"


def read_requirements(path: Path) -> list[str]:
    """Returns the requirement lines of a requirements file, without comments or blank lines."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split(" #")[0].strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def requirement_name(line: str) -> str:
    """Returns the normalised distribution name a requirement line installs (extras and pins removed)."""
    return normalise_python_name(re.split(r"[\[=<>!~; ]", line, maxsplit=1)[0])


def requirement_pin(line: str) -> str | None:
    """Returns the exact version of a `name==version` requirement, or None when it is not pinned."""
    match = re.search(r"==\s*([^\s;]+)", line)
    return match.group(1) if match else None


def collect_python(component: str, policy: dict) -> list[Package]:
    """Installs a requirements file in a throwaway environment and returns its packages with their licences.

    Args:
        component: A key of PYTHON_COMPONENTS.
        policy: The parsed licence policy.

    Returns:
        Every installed distribution except the installer tooling.

    Raises:
        subprocess.CalledProcessError: If the environment cannot be built or the requirements cannot be installed.
    """
    requirements = ROOT / PYTHON_COMPONENTS[component]
    direct = {requirement_name(line) for line in read_requirements(requirements)}
    with tempfile.TemporaryDirectory(prefix="licence-venv-") as tmp:
        env = Path(tmp) / "env"
        subprocess.run([sys.executable, "-m", "venv", str(env)], check=True)
        python = env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-input", "-r", str(requirements)],
            check=True,
        )
        out = subprocess.run([str(python), "-I", "-c", _COLLECTOR], check=True, capture_output=True, text=True).stdout
    packages = []
    for raw in json.loads(out):
        name = normalise_python_name(raw["name"])
        if name in IGNORED_PYTHON_DISTRIBUTIONS:
            continue
        licence, source = resolve_python_licence(raw, policy)
        package = Package("python", name, raw["version"], {component}, name in direct, licence, source)
        package.files = raw["files"]
        packages.append(package)
    return sorted(packages, key=lambda p: p.name)


def npm_package_name(path: str) -> str:
    """Returns the package name from a lockfile path such as `node_modules/a/node_modules/@s/b`."""
    return path.rsplit("node_modules/", 1)[-1]


_TEXT_FILE = re.compile(r"^(licen[cs]e|copying|notice|unlicen[cs]e)", re.IGNORECASE)


def read_npm_licence_files(project: Path, lock_path: str) -> list[tuple[str, str]]:
    """Returns `(file name, text)` for each licence file in an installed package directory, or an empty list."""
    directory = project / lock_path
    if not directory.is_dir():
        return []
    found = []
    for child in sorted(directory.iterdir()):
        if child.is_file() and _TEXT_FILE.match(child.name) and child.resolve().is_relative_to(directory.resolve()):
            found.append((child.name, child.read_text(encoding="utf-8", errors="replace")))
    return found


def npm_declared_licence(package_json: Path) -> str | None:
    """Returns the licence an installed package.json declares, for a lockfile entry that omits it."""
    if not package_json.is_file():
        return None
    data = json.loads(package_json.read_text(encoding="utf-8"))
    value = data.get("license")
    if isinstance(value, dict):
        value = value.get("type")
    if value is None and isinstance(data.get("licenses"), list) and data["licenses"]:
        value = data["licenses"][0].get("type")
    return value


def collect_npm(component: str, policy: dict, with_texts: bool = False) -> list[Package]:
    """Returns the production packages of an npm lockfile with their declared licences.

    Args:
        component: A key of NPM_COMPONENTS.
        policy: The parsed licence policy (overrides win over the lockfile).
        with_texts: Also read each package's licence files from the installed `node_modules` (used when generating).

    Returns:
        Every non-development, non-linked package, one entry per name and version.
    """
    project = ROOT / NPM_COMPONENTS[component]
    lock = json.loads((project / "package-lock.json").read_text(encoding="utf-8"))
    root = lock["packages"].get("", {})
    direct = set(root.get("dependencies", {}))
    found: dict[tuple[str, str], Package] = {}
    for path, entry in lock["packages"].items():
        if not path or entry.get("dev") or entry.get("link"):
            continue
        name = npm_package_name(path)
        licence = entry.get("license")
        source = "metadata"
        if not licence:
            licence = npm_declared_licence(project / path / "package.json")
            source = "package.json"
        override = policy["overrides"].get(f"npm:{name}")
        if override:
            licence, source = override["licence"], "override"
        package = Package("npm", name, entry["version"], {component}, name in direct and path == f"node_modules/{name}")
        package.licence = licence if isinstance(licence, str) and licence else "UNKNOWN"
        package.licence_source = source if licence else "none"
        if with_texts:
            package.files = [list(t) for t in read_npm_licence_files(project, path)]
        found.setdefault((name, entry["version"]), package)
    return sorted(found.values(), key=lambda p: (p.name, p.version))


def parse_dockerfile_packages(text: str) -> set[str]:
    """Returns the operating-system packages named by `apt-get install` and `apk add` in a Dockerfile's text.

    Arguments are read up to the next shell operator and options are skipped. A package a later step purges is
    still named, because it is present in an intermediate layer.
    """
    text = re.sub(r"\\\n", " ", text)
    text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    packages: set[str] = set()
    for match in re.finditer(r"(?:apt-get install|apk add)((?:(?!&&|\|\||;)[^\n])*)", text):
        packages.update(token for token in match.group(1).split() if not token.startswith("-"))
    return packages


def dockerfile_system_packages() -> dict[str, set[str]]:
    """Returns the operating-system packages each Dockerfile installs, by Dockerfile path (perf tooling excluded)."""
    found: dict[str, set[str]] = {}
    for path in sorted(ROOT.rglob("Dockerfile*")):
        if set(path.relative_to(ROOT).parts) & {"node_modules", ".git", "build", "graphify-out", "perf"}:
            continue
        packages = parse_dockerfile_packages(path.read_text(encoding="utf-8"))
        if packages:
            found[str(path.relative_to(ROOT))] = packages
    return found


def merge(packages: list[Package]) -> list[Package]:
    """Merges the same package (ecosystem, name, version) across components into one entry listing every component."""
    merged: dict[tuple[str, str, str], Package] = {}
    for package in packages:
        key = (package.ecosystem, package.name, package.version)
        if key in merged:
            merged[key].components |= package.components
            merged[key].direct = merged[key].direct or package.direct
            if not merged[key].files:
                merged[key].files = package.files
        else:
            merged[key] = package
    return sorted(merged.values(), key=lambda p: (p.ecosystem, p.name, p.version))


OUTPUT_DIR = ROOT / "frontend" / "public" / "licences"
NOTICES_PATH = OUTPUT_DIR / "third-party-notices.json"
TEXTS_PATH = OUTPUT_DIR / "third-party-texts.json"
COPYLEFT_USES_ALLOWED = {"separate-program", "build-tool"}
COPYLEFT_PREFIXES = ("gpl", "agpl", "lgpl")
FROM_LINE = re.compile(r"^FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", re.IGNORECASE | re.MULTILINE)


def judge_system_component(component: dict) -> str:
    """Judges one operating-system component of an image.

    Copyleft (GPL, AGPL, LGPL) is allowed only for a program run as a separate process, or a build tool; a library
    the application links must be permissive. The component must also state why.

    Returns:
        `ok`, or a sentence naming why it fails.
    """
    licence = component["licence"]
    ids = [t for t in re.split(r"[\s()]+", licence) if t and t.upper() not in {"AND", "OR", "WITH"}]
    copyleft = any(i.lower().startswith(COPYLEFT_PREFIXES) for i in ids)
    if copyleft and component.get("use") not in COPYLEFT_USES_ALLOWED:
        return f"{component['name']} is {licence} but is used as '{component.get('use')}', not a separate program or build tool"
    if copyleft and not component.get("reason"):
        return f"{component['name']} is copyleft and states no reason"
    return "ok"


def dockerfile_base_images() -> set[str]:
    """Returns every external image a Dockerfile builds from (stage aliases such as `FROM base` are skipped)."""
    images: set[str] = set()
    for path in sorted(ROOT.rglob("Dockerfile*")):
        if set(path.relative_to(ROOT).parts) & {"node_modules", ".git", "build", "graphify-out", "perf"}:
            continue
        text = path.read_text(encoding="utf-8")
        aliases = {m.group(2).lower() for m in FROM_LINE.finditer(text) if m.group(2)}
        for match in FROM_LINE.finditer(text):
            if match.group(1).lower() not in aliases:
                images.add(match.group(1))
    return images


def check_policy(policy: dict, inventory: dict) -> list[str]:
    """Judges a generated inventory and the Dockerfiles against the policy; returns one message per failure.

    Args:
        policy: The parsed licence policy.
        inventory: The parsed third-party notices file.
    """
    problems = []
    for package in inventory["packages"]:
        key = f"{package['ecosystem']}:{package['name']}"
        verdict = judge_licence(policy, key, package["licence"])
        if verdict not in ("ok", "notice"):
            problems.append(f"{key}@{package['version']}: {verdict} (licence '{package['licence']}')")
    for component in policy["system_components"]:
        verdict = judge_system_component(component)
        if verdict != "ok":
            problems.append(verdict)
    known = {p for c in policy["system_components"] for p in c["packages"]}
    for dockerfile, packages in dockerfile_system_packages().items():
        for package in sorted(packages - known):
            problems.append(f"{dockerfile} installs '{package}', which the policy's system_components does not name")
    installed = set().union(*dockerfile_system_packages().values())
    for component in policy["system_components"]:
        for package in component["packages"]:
            if package not in installed:
                problems.append(f"policy names system package '{package}' that no Dockerfile installs (remove it)")
    for image in sorted(dockerfile_base_images() - set(policy["base_images"])):
        problems.append(f"a Dockerfile builds from '{image}', which the policy's base_images does not name")
    for image in sorted(set(policy["base_images"]) - dockerfile_base_images()):
        problems.append(f"policy names base image '{image}' that no Dockerfile uses (remove it)")
    for font in policy["fonts"]:
        if judge_licence(policy, f"font:{font['name']}", font["licence"]) not in ("ok", "notice"):
            problems.append(f"font {font['name']}: licence '{font['licence']}' is not in the policy")
        if font.get("text") and not (ROOT / font["text"]).is_file():
            problems.append(f"font {font['name']}: licence text {font['text']} is missing")
    return problems


def check_inventory_current(policy: dict, inventory: dict) -> list[str]:
    """Compares a generated inventory with the lockfiles and requirements files; returns one message per difference.

    npm lockfiles are compared exactly (name, version, licence). A Python requirements file is compared by its
    direct requirements only, because transitive versions float between builds (regenerate to pick them up).
    """
    problems = []
    index = {(p["ecosystem"], p["name"], p["version"]): p for p in inventory["packages"]}
    for component in NPM_COMPONENTS:
        expected = {(p.name, p.version): p.licence for p in collect_npm(component, policy)}
        actual = {(k[1], k[2]): p["licence"] for k, p in index.items() if k[0] == "npm" and component in p["components"]}
        for (name, version), licence in sorted(expected.items()):
            if actual.get((name, version)) != licence:
                problems.append(f"{component}: {name}@{version} is missing or has another licence in the inventory")
        for name, version in sorted(set(actual) - set(expected)):
            problems.append(f"{component}: {name}@{version} is in the inventory but not in the lockfile")
    for component, requirements in PYTHON_COMPONENTS.items():
        listed = {p["name"]: p for p in inventory["packages"] if p["ecosystem"] == "python" and component in p["components"]}
        for line in read_requirements(ROOT / requirements):
            name, pin = requirement_name(line), requirement_pin(line)
            entry = listed.get(name)
            if entry is None:
                problems.append(f"{component}: {name} is in {requirements} but not in the inventory")
            elif pin and entry["version"] != pin:
                problems.append(f"{component}: {name} is pinned to {pin} but the inventory has {entry['version']}")
    return problems
