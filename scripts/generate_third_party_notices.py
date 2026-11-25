#!/usr/bin/env python3
"""
Module: generate_third_party_notices

Writes the inventory of third-party components the product ships, with their licences and licence texts.

Outputs (committed, served as static assets by the front end so the Licences page can read them):
- frontend/public/licences/third-party-notices.json: every package, system component and font with its SPDX licence.
- frontend/public/licences/third-party-texts.json: the licence files, keyed by a hash of their text, so identical
  texts are stored once.

Usage:
    python scripts/generate_third_party_notices.py          # regenerate (needs network and installed node_modules)
    python scripts/generate_third_party_notices.py --check  # fail if the committed inventory is stale (offline)

Design decisions: npm packages come from the lockfiles and their texts from the installed `node_modules` (run `npm ci`
in `frontend/` and `docs/website/` first); a package whose platform-specific build is not installed on this machine has
no text and says so. Python packages come from a throwaway environment per requirements file. The output is sorted and
contains no timestamps, so a run on unchanged inputs changes nothing.

Used by: developers when a lockfile or requirements file changes, and the `licences` CI job (`--check`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import licence_inventory as inv  # noqa: E402

MAX_TEXT_BYTES = 120_000
COMPONENT_TITLES = {
    "backend": "Backend API image",
    "mcp-server": "MCP server image",
    "converter": "Picture and diagram converter image",
    "frontend": "Front-end application (bundled)",
    "docs": "Documentation site (bundled)",
}


def add_text(texts: dict[str, str], text: str) -> str:
    """Stores a licence text once and returns its id (the first 12 hex digits of its SHA-256).

    Args:
        texts: The id-to-text map being built.
        text: The licence text; line endings are normalised and a text over the size cap is truncated with a marker.
    """
    body = text.replace("\r\n", "\n").rstrip() + "\n"
    if len(body.encode("utf-8")) > MAX_TEXT_BYTES:
        body = body.encode("utf-8")[:MAX_TEXT_BYTES].decode("utf-8", "ignore") + "\n[truncated; the package carries the full text]\n"
    text_id = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    texts[text_id] = body
    return text_id


def package_link(package: inv.Package) -> str:
    """Returns the registry page of a package version."""
    if package.ecosystem == "npm":
        return f"https://www.npmjs.com/package/{package.name}/v/{package.version}"
    return f"https://pypi.org/project/{package.name}/{package.version}/"


def build(policy: dict) -> tuple[dict, dict[str, str]]:
    """Collects every component and returns the notices document and the texts map.

    Raises:
        subprocess.CalledProcessError: If a Python requirements file cannot be installed.
    """
    collected: list[inv.Package] = []
    for component in inv.PYTHON_COMPONENTS:
        print(f"resolving {component} ...", flush=True)
        collected += inv.collect_python(component, policy)
    for component in inv.NPM_COMPONENTS:
        print(f"reading {component} lockfile ...", flush=True)
        collected += inv.collect_npm(component, policy, with_texts=True)
    texts: dict[str, str] = {}
    packages = []
    for package in inv.merge(collected):
        verdict = inv.judge_licence(policy, package.key, package.licence)
        text_ids = sorted({add_text(texts, text) for _, text in package.files if text.strip()})
        packages.append(
            {
                "ecosystem": package.ecosystem,
                "name": package.name,
                "version": package.version,
                "components": sorted(package.components),
                "direct": package.direct,
                "licence": package.licence,
                "licence_source": package.licence_source,
                "review": "notice" if verdict == "notice" else "none",
                "texts": text_ids,
                "link": package_link(package),
            }
        )
    fonts = []
    for font in policy["fonts"]:
        entry = {k: v for k, v in font.items() if k != "text"}
        entry["texts"] = [add_text(texts, (inv.ROOT / font["text"]).read_text(encoding="utf-8"))] if font.get("text") else []
        fonts.append(entry)
    notices = {
        "schema": 1,
        "generator": "scripts/generate_third_party_notices.py",
        "python_resolved_with": f"{sys.version_info.major}.{sys.version_info.minor}",
        "components": [{"id": key, "title": title} for key, title in COMPONENT_TITLES.items()],
        "packages": packages,
        "system_components": policy["system_components"],
        "base_images": policy["base_images"],
        "fonts": fonts,
        "library_copyleft_reasons": policy["library_copyleft_reasons"],
        "notes": policy["notes"],
        "packages_without_text": sum(1 for p in packages if not p["texts"]),
    }
    return notices, texts


def dump(data: dict) -> str:
    """Serialises a document with sorted keys and a trailing newline so repeated runs are byte-identical."""
    return json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Entry point: regenerates the inventory, or with `--check` reports whether the committed one is current.

    Returns:
        0 on success, 1 if `--check` finds the inventory stale.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if the committed inventory differs from the lockfiles")
    args = parser.parse_args(argv)
    policy = inv.load_policy()
    if args.check:
        if not inv.NOTICES_PATH.is_file():
            print(f"{inv.NOTICES_PATH} is missing; run scripts/generate_third_party_notices.py")
            return 1
        problems = inv.check_inventory_current(policy, json.loads(inv.NOTICES_PATH.read_text(encoding="utf-8")))
        for problem in problems:
            print(problem)
        if problems:
            print("The third-party inventory is stale: run `python scripts/generate_third_party_notices.py` and commit the result.")
        return 1 if problems else 0
    notices, texts = build(policy)
    inv.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    inv.NOTICES_PATH.write_text(dump(notices), encoding="utf-8")
    inv.TEXTS_PATH.write_text(dump(texts), encoding="utf-8")
    print(f"{len(notices['packages'])} packages, {len(texts)} licence texts, {notices['packages_without_text']} packages without a text")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
