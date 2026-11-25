#!/usr/bin/env python3
"""
Module: check_cla

Fails a pull request whose commit authors have not signed the current contributor licence agreement.

Why: the product is offered under the AGPL and a commercial licence, which needs every contributor to have granted
the licensor the right to do both (CLA.md). A contribution accepted without that grant cannot be relicensed later.

Responsibilities:
- Validate `.github/cla-signatories.json` (shape, unique logins, date format, no maintainer or automation account
  also listed as a signatory).
- Read the current agreement version from the first `**Version x.y**` line of CLA.md.
- With `--authors`, require every GitHub login to be a maintainer, an automation account, or a signatory whose
  recorded `cla_version` equals the current version. An empty login (a commit email not linked to a GitHub account)
  always fails, because it cannot be matched to a signature.

Design decisions: the pull request's opener (authenticated by GitHub) is checked as well as the commit authors,
because a commit's author is only an attribution anyone can forge by writing another person's email into it. A
signature is a reviewed entry in the repository (CODEOWNERS review applies), so no third-party application with
write access is needed. Standard library only.

On a pull request the maintainer and automation lists are read from the base branch's copy of the file, so a pull
request cannot exempt its own author.

Used by: the `cla` CI job (pull requests), `backend/tests/test_cla_check.py` and, validating the file alone,
.githooks/pre-commit.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIGNATORIES = ROOT / ".github" / "cla-signatories.json"
AGREEMENT = ROOT / "CLA.md"
VERSION_LINE = re.compile(r"^\*\*Version (\d+(?:\.\d+)*)\*\*\s*$", re.MULTILINE)


def current_version(agreement_text: str) -> str:
    """Returns the agreement version stated in the text of CLA.md.

    Args:
        agreement_text: The full text of CLA.md.

    Returns:
        The version string, for example "1.0".

    Raises:
        ValueError: If the text has no `**Version x.y**` line.
    """
    match = VERSION_LINE.search(agreement_text)
    if match is None:
        raise ValueError("CLA.md has no '**Version x.y**' line")
    return match.group(1)


def file_problems(data: dict) -> list[str]:
    """Validates the signatories file and returns one message per problem.

    Args:
        data: The parsed `.github/cla-signatories.json`.

    Returns:
        Problem messages; empty when the file is well formed.
    """
    problems: list[str] = []
    for key in ("maintainers", "automation"):
        value = data.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            problems.append(f"'{key}' must be a list of GitHub logins")
    signatories = data.get("signatories")
    if not isinstance(signatories, list):
        return [*problems, "'signatories' must be a list"]
    seen: set[str] = set()
    exempt = {login.lower() for key in ("maintainers", "automation") for login in data.get(key, []) if isinstance(login, str)}
    for entry in signatories:
        login = entry.get("login") if isinstance(entry, dict) else None
        if not isinstance(login, str) or not login:
            problems.append(f"a signatory has no login: {entry!r}")
            continue
        if login.lower() in seen:
            problems.append(f"'{login}' is listed more than once")
        seen.add(login.lower())
        if login.lower() in exempt:
            problems.append(f"'{login}' is a maintainer or automation account and needs no signature")
        if not isinstance(entry.get("name"), str) or not entry["name"].strip():
            problems.append(f"'{login}' has no name")
        try:
            date.fromisoformat(str(entry.get("date")))
        except ValueError:
            problems.append(f"'{login}' has no valid date (YYYY-MM-DD)")
        if not isinstance(entry.get("cla_version"), str) or not re.fullmatch(r"\d+(\.\d+)*", entry["cla_version"]):
            problems.append(f"'{login}' has no valid cla_version")
    return problems


def author_problems(data: dict, trusted: dict, version: str, authors: list[str]) -> list[str]:
    """Returns one message per author who has not signed the current agreement.

    Args:
        data: The parsed `.github/cla-signatories.json` of the pull request (its signatories are the signatures).
        trusted: The same file from the base branch; only its maintainers and automation lists exempt an author, so a
            pull request cannot exempt itself.
        version: The current agreement version.
        authors: GitHub logins of the pull request's commit authors; an empty string stands for an unlinked author.

    Returns:
        Problem messages; empty when every author is covered.
    """
    exempt = {login.lower() for key in ("maintainers", "automation") for login in trusted.get(key, [])}
    signed = {
        entry["login"].lower(): entry.get("cla_version")
        for entry in data.get("signatories", [])
        if isinstance(entry, dict) and "login" in entry
    }
    problems: list[str] = []
    for login in sorted(set(authors)):
        if not login:
            problems.append("a commit's author is not linked to a GitHub account; use a verified email of your account")
        elif login.lower() in exempt:
            continue
        elif login.lower() not in signed:
            problems.append(f"'{login}' has not signed CLA.md; add an entry to .github/cla-signatories.json (see CONTRIBUTING.md)")
        elif signed[login.lower()] != version:
            problems.append(f"'{login}' signed version {signed[login.lower()]}; the current version is {version}")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Runs the check.

    Args:
        argv: Command-line arguments; `--authors LOGIN...` checks pull request authors as well as the file.

    Returns:
        0 when everything passes, 1 otherwise (problems are printed to standard error).
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--authors", nargs="*", default=None, help="GitHub logins of the commit authors to check")
    parser.add_argument("--base-file", type=Path, default=None, help="signatories file from the base branch (default: the working copy)")
    args = parser.parse_args(argv)
    try:
        version = current_version(AGREEMENT.read_text(encoding="utf-8"))
        data = json.loads(SIGNATORIES.read_text(encoding="utf-8"))
        trusted = json.loads(args.base_file.read_text(encoding="utf-8")) if args.base_file else data
    except (OSError, ValueError) as error:
        print(f"check_cla: {error}", file=sys.stderr)
        return 1
    problems = file_problems(data)
    if args.authors is not None:
        problems += author_problems(data, trusted, version, args.authors)
    for problem in problems:
        print(f"check_cla: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
