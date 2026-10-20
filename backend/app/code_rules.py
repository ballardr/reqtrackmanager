"""
Module: code_rules

Pure rules for the short codes that identify a project (and an organisation)
inside a qualified record code such as `ACME-REQ-001`: the character kinds,
the organisation's code policy, validation, and candidate generation from a
name.

Responsibilities:
- Describe the organisation policy (`CodePolicy`) and its defaults.
- Validate a code against a policy, returning a message rather than raising.
- Yield candidate codes derived from a name, best first, for the caller to
  filter against codes already taken.

Design decisions:
- No database, no framework: models use `default_code_for_name` as a column
  default and migrations copy the rules, so this module imports nothing from
  the app.
- Codes are stored upper-case, so a plain unique constraint is
  case-insensitive. A hyphen is never allowed: a qualified code is split on
  its first hyphen, so neither a project nor an organisation code may contain
  one.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

CodeKind = Literal["letters", "digits", "alphanumeric"]
CodeAssignment = Literal["auto", "manual"]

CODE_KINDS: tuple[str, ...] = ("letters", "digits", "alphanumeric")
CODE_ASSIGNMENTS: tuple[str, ...] = ("auto", "manual")

# Upper bound on any policy's maximum length, and the length of an organisation code.
ABSOLUTE_MAX_CODE_LENGTH = 10
MAX_GENERATION_ATTEMPTS = 10_000

_ALPHABET: dict[str, re.Pattern[str]] = {
    "letters": re.compile(r"[A-Z]"),
    "digits": re.compile(r"[0-9]"),
    "alphanumeric": re.compile(r"[A-Z0-9]"),
}
_WORD = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True)
class CodePolicy:
    """How an organisation's project codes are formed.

    Attributes:
        kind: Allowed characters: `letters`, `digits` or `alphanumeric`.
        min_length: Fewest characters a code may have (at least 1).
        max_length: Most characters a code may have (at most `ABSOLUTE_MAX_CODE_LENGTH`).
        assignment: `auto` has the server generate every code; `manual` has the
            creator choose it.
    """

    kind: str = "alphanumeric"
    min_length: int = 2
    max_length: int = 6
    assignment: str = "auto"

    def as_dict(self) -> dict[str, str | int]:
        """The policy as the plain mapping stored on `Organization.project_code_policy`."""
        return {
            "kind": self.kind, "min_length": self.min_length, "max_length": self.max_length,
            "assignment": self.assignment,
        }

    @classmethod
    def from_mapping(cls, stored: dict | None) -> CodePolicy:
        """Builds a policy from a stored mapping, filling missing keys with the defaults."""
        merged = {**DEFAULT_POLICY.as_dict(), **(stored or {})}
        return cls(
            kind=str(merged["kind"]), min_length=int(merged["min_length"]), max_length=int(merged["max_length"]),
            assignment=str(merged["assignment"]),
        )


DEFAULT_POLICY = CodePolicy()


def policy_error(policy: CodePolicy) -> str | None:
    """A message describing why `policy` is not a usable policy, or `None` when it is."""
    if policy.kind not in CODE_KINDS:
        return f"Code kind must be one of {', '.join(CODE_KINDS)}."
    if policy.assignment not in CODE_ASSIGNMENTS:
        return f"Code assignment must be one of {', '.join(CODE_ASSIGNMENTS)}."
    if not 1 <= policy.min_length <= policy.max_length <= ABSOLUTE_MAX_CODE_LENGTH:
        return f"Code lengths must satisfy 1 <= minimum <= maximum <= {ABSOLUTE_MAX_CODE_LENGTH}."
    return None


def normalise_code(raw: str) -> str:
    """The stored form of a code: surrounding whitespace removed, upper-cased."""
    return raw.strip().upper()


def code_error(code: str, policy: CodePolicy) -> str | None:
    """A message describing why the (normalised) `code` breaks `policy`, or `None` when it conforms.

    Args:
        code: The code, already passed through `normalise_code`.
        policy: The organisation's policy.
    """
    alphabet = _ALPHABET[policy.kind]
    if not code or any(alphabet.fullmatch(ch) is None for ch in code):
        allowed = {"letters": "letters A-Z", "digits": "digits 0-9", "alphanumeric": "letters A-Z and digits 0-9"}
        return f"A project code may only use {allowed[policy.kind]}, with no spaces or hyphens."
    if not policy.min_length <= len(code) <= policy.max_length:
        return f"A project code must be {policy.min_length} to {policy.max_length} characters long."
    return None


def _suffix(n: int, kind: str) -> str:
    """The disambiguating tail for the nth collision (n >= 2): a number, or letters for a letters-only policy."""
    if kind != "letters":
        return str(n)
    n -= 1  # 2 -> B
    letters = ""
    while n > 0:
        n, rem = divmod(n, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _base_from_name(name: str, policy: CodePolicy) -> str:
    """The name's initials, lengthened with its following characters up to the minimum and truncated to the maximum."""
    alphabet = _ALPHABET[policy.kind]
    words = [w.upper() for w in _WORD.findall(name)]
    base = "".join(next((c for c in w if alphabet.fullmatch(c)), "") for w in words)
    if len(base) < policy.min_length:
        rest = "".join(c for w in words for c in w[1:] if alphabet.fullmatch(c))
        base += rest[: policy.min_length - len(base)]
    if len(base) < policy.min_length:
        base += "X" * (policy.min_length - len(base))
    return base[: policy.max_length]


def candidate_codes(name: str, policy: CodePolicy) -> Iterator[str]:
    """Yields codes derived from `name` that conform to `policy`, best first.

    The first is the name's initials (`Rail Signalling Upgrade` -> `RSU`); later ones add
    a disambiguating suffix. A digits-only policy cannot use a name, so it counts upward.
    Every yielded code conforms; the caller drops those already taken.

    Args:
        name: The project or organisation name.
        policy: The policy the codes must satisfy.
    """
    if policy.kind == "digits":
        for n in range(1, MAX_GENERATION_ATTEMPTS):
            candidate = str(n).zfill(policy.min_length)
            if len(candidate) > policy.max_length:
                return
            yield candidate
        return
    base = _base_from_name(name, policy)
    if len(base) < policy.min_length:
        return
    yield base
    for n in range(2, MAX_GENERATION_ATTEMPTS):
        tail = _suffix(n, policy.kind)
        if len(tail) >= policy.max_length:
            return
        yield base[: policy.max_length - len(tail)] + tail


def default_code_for_name(name: str) -> str:
    """The first conforming code for `name` under the default policy; used as the
    organisation-code column default and the fallback for an unusable name."""
    return next(candidate_codes(name, DEFAULT_POLICY), "XX")
