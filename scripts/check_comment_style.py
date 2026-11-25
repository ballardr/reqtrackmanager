#!/usr/bin/env python3
"""
Module: check_comment_style

Fails when a source comment or docstring narrates how the code got here instead of
describing what it implements (CLAUDE.md "Code Comments Describe the Code").

Detected in every tracked source file (Python, TypeScript, JavaScript, CSS, shell, YAML,
Dockerfile, TOML, INI, Caddyfile):
- conversational or review wording ("the user asked", "as discussed", "found in review");
- a calendar date or a month and year ("2026-11-23", "Nov 2026");
- history wording ("previously", "used to", "no longer", "was changed from", "the fix for");
- a plan document or phase reference (also enforced by check_doc_links.py).

A comment that must keep one of these words for a real reason (a domain term such as a user
who "asked" for a password reset) carries the marker `comment-style-ok: <reason>`.

`--candidates` additionally prints the judgement items a script cannot decide: a comment
block of more than BLOCK_LIMIT lines and a module docstring of more than MODULE_DOC_LIMIT
lines. They never fail the check; reviewers shorten them or state why they cannot be shorter.

Design notes:
- Comments are extracted with a tokenizer, not a line regex, so a string that merely contains
  `//` or `#` (a URL, a colour, a pattern) is never read as a comment. Python uses `tokenize`
  and `ast` (docstrings); the C-style scanner skips strings, template literals and regular
  expression literals; `#` files take whole-line comments and trailing comments after a space.
- Words with an everyday domain meaning (`now`, `user`, `after`) are flagged only in the
  phrases that tell a story, so the check stays free of exemptions in normal use.

Usage: python scripts/check_comment_style.py              (exit 1 and a list on failure)
       python scripts/check_comment_style.py --staged     (only the staged files)
       python scripts/check_comment_style.py --candidates (also list over-long blocks)
Dependencies: standard library and `git` only. Also run by backend/tests/test_comment_style.py
when the repository is available.
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import sys
import tokenize
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BLOCK_LIMIT = 3
MODULE_DOC_LIMIT = 10

# The line Alembic writes into every migration's docstring.
GENERATED_HEADER = re.compile(r"^Create Date:.*$", re.M)

# Marker that exempts one comment, followed by the reason it must keep the wording.
EXEMPT_MARKER = "comment-style-ok:"

PYTHON_SUFFIXES = {".py"}
C_STYLE_SUFFIXES = {".ts", ".tsx", ".js", ".mjs", ".css"}
HASH_SUFFIXES = {".sh", ".yml", ".yaml", ".toml", ".ini", ".caddy"}
HASH_NAMES = {"Dockerfile"}

# Vendored, generated and demonstration-data files carry text that is not this project's commentary.
SKIP_PREFIXES = (
    "backend/scripts/data/",
    "docs/",
    "frontend/node_modules/",
    "frontend/public/",
    "frontend/storybook-static/",
    "tests/container/report-fonts/",
    ".claude/",
)
# Files that must contain the flagged wording to do their job.
SELF_EXEMPT = {"scripts/check_comment_style.py", "backend/tests/test_comment_style.py"}

_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december"

# (label, pattern). All case-insensitive and matched against the comment text.
RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "conversational or review wording",
        re.compile(
            r"\b(?:"
            r"the user (?:asked|wanted|said|reported|corrected|raised|complained|pointed|decided|requested that)"
            r"|(?:user|users|reviewer|reviewers|customer|you) (?:asked|requested|reported|complained) (?:for|that|about)"
            r"|as (?:discussed|agreed|requested|reported|noted in (?:the )?(?:review|chat|conversation))"
            r"|per (?:the )?(?:review|user'?s? (?:request|ask)|chat|conversation|feedback)"
            r"|(?:found|raised|reported|flagged|noticed|caught|spotted|identified) (?:in|during|by|at) (?:a |the |an )?"
            r"(?:review|code review|audit|hardening|pass|session|chat|conversation|testing|e2e|ci)"
            r"|(?:hardening[- ])?review finding|(?:audit|reviewer|bug|incident|customer) (?:finding|report|feedback|comment|request)"
            r"|we (?:decided|agreed|discussed|chose|found|noticed)"
            r"|the (?:conversation|chat|discussion) (?:above|earlier|before)"
            r"|in (?:this|the) (?:chat|conversation|session|pull request|pr|review)"
            r"|(?:bug|issue|pr|pull request) ?#\d+"
            r")\b",
            re.I,
        ),
    ),
    (
        "date",
        re.compile(
            r"\b20\d\d-[01]\d-[0-3]\d\b|\b(?:" + _MONTHS + r")\.? (?:[0-3]?\d(?:st|nd|rd|th)?,? )?20\d\d\b",
            re.I,
        ),
    ),
    (
        "history wording",
        re.compile(
            r"\b(?:previously(?!-?\s*\w+(?:ed|en|wn)\b)|formerly|used to be|"
            r"(?:this|that|which|it|what|they|these|those|code|version|form|column|page|rule) used to|"
            r"no longer (?:accepts?|takes?|reads?|uses?|returns?|needs?|requires?|calls?|renders?|shows?|draws?|offers?|"
            r"has|have|does|do|goes|lives|carries|holds|sends|writes|stores|builds|gets|had|needed|required|used)|"
            r"was changed (?:from|to)|was renamed|has been (?:renamed|moved|removed|changed|fixed|replaced)|"
            r"have been (?:renamed|moved|removed|changed|fixed|replaced)|"
            r"the fix for|the fix is|a fix for|now fixed|originally|since removed|"
            r"(?:older|previous|former|old) (?:behaviou?r|implementation|code|name)|earlier (?:behaviou?r|implementation|name)|"
            r"(?:before|after) (?:the|this) (?:fix|refactor|migration|rewrite|bug)|"
            r"(?:was|were) (?:added|introduced|removed|replaced) (?:in|by|to fix|because|after)|"
            r"now lives|now (?:fixed|correct|correctly|properly)"
            r")\b",
            re.I,
        ),
    ),
    (
        "plan or phase reference",
        # The plans directory is spelled in two parts so check_doc_links.py does not read this rule as a citation.
        re.compile(r"\b[Pp]hases? (?:\d+[a-z]?|[A-E])\b|\bdocs/" + "plans/"),
    ),
]

@dataclass(frozen=True)
class CommentBlock:
    """One comment or docstring: where it starts, its text and how many lines it spans."""

    line: int
    text: str
    lines: int
    kind: str  # "comment", "docstring" or "module-docstring"


def tracked_files() -> list[str]:
    """
    Lists git-tracked files this check scans.

    Returns:
        Repo-relative POSIX paths with a scanned suffix or name, minus skipped trees and this check itself.
    """
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    return [f for f in out.splitlines() if is_scanned(f)]


def is_scanned(rel: str) -> bool:
    """
    Says whether a repo-relative path is a source file this check reads.

    Args:
        rel: Repo-relative POSIX path.

    Returns:
        True for a source or configuration file outside the skipped trees.
    """
    if rel in SELF_EXEMPT or rel.startswith(SKIP_PREFIXES):
        return False
    path = Path(rel)
    name = path.name
    return (
        path.suffix in PYTHON_SUFFIXES | C_STYLE_SUFFIXES | HASH_SUFFIXES
        or name in HASH_NAMES
        or name.startswith("Dockerfile")
        or name == "Caddyfile"
    )


def python_comments(text: str) -> Iterator[CommentBlock]:
    """
    Yields every comment and docstring in Python source.

    Args:
        text: The file's source.

    Yields:
        A CommentBlock per `#` comment (a run of consecutive comment lines is one block) and per docstring.
        A file that does not parse yields only its comments.
    """
    pending: list[tuple[int, str]] = []

    def flush() -> Iterator[CommentBlock]:
        if pending:
            yield CommentBlock(pending[0][0], "\n".join(t for _, t in pending), len(pending), "comment")
            pending.clear()

    last_line = -2
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type != tokenize.COMMENT:
                continue
            body = tok.string.lstrip("#").strip()
            if tok.start[0] == 1 and tok.string.startswith("#!"):
                continue
            own_line = tok.line.strip().startswith("#")
            if own_line and tok.start[0] == last_line + 1 and pending:
                pending.append((tok.start[0], body))
            else:
                yield from flush()
                if own_line:
                    pending.append((tok.start[0], body))
                else:
                    yield CommentBlock(tok.start[0], body, 1, "comment")
            last_line = tok.start[0] if own_line else -2
        yield from flush()
    except (tokenize.TokenError, IndentationError, SyntaxError):
        yield from flush()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            doc = value.value
            end = getattr(value, "end_lineno", value.lineno) or value.lineno
            yield CommentBlock(
                value.lineno,
                doc,
                max(1, end - value.lineno + 1),
                "module-docstring" if isinstance(node, ast.Module) else "docstring",
            )


def c_style_comments(text: str) -> Iterator[CommentBlock]:
    """
    Yields every `//` and `/* */` comment in TypeScript, JavaScript or CSS source.

    The scanner skips single- and double-quoted strings (which end at a line break, so an apostrophe in JSX text
    cannot swallow the file), template literals (including nested `${}` expressions) and regular expression
    literals. `//` directly after a colon is a URL, not a comment. Consecutive `//` lines form one block.

    Args:
        text: The file's source.

    Yields:
        A CommentBlock per block comment and per run of line comments.
    """
    i, n, line = 0, len(text), 1
    run: list[tuple[int, str]] = []
    run_end = -2
    template_depth: list[int] = []  # brace depth at which each open `${` resumes the template
    brace = 0
    prev_sig = ""  # last significant character, to tell a regex from a division

    def flush_run() -> Iterator[CommentBlock]:
        if run:
            yield CommentBlock(run[0][0], "\n".join(t for _, t in run), len(run), "comment")
            run.clear()

    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "\n":
            line += 1
            i += 1
            continue
        if c == "/" and nxt == "/" and (i == 0 or text[i - 1] != ":"):
            end = text.find("\n", i)
            end = n if end == -1 else end
            body = text[i + 2 : end].strip()
            if run and line == run_end + 1 and text[:i].rsplit("\n", 1)[-1].strip() == "":
                run.append((line, body))
            else:
                yield from flush_run()
                run.append((line, body))
            run_end = line
            if text[:i].rsplit("\n", 1)[-1].strip() != "":
                yield from flush_run()
                run_end = -2
            i = end
            continue
        if c == "/" and nxt == "*":
            yield from flush_run()
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            chunk = text[i:end]
            span = chunk.count("\n") + 1
            body = "\n".join(re.sub(r"^\s*\*?\s?", "", part) for part in chunk[2:-2].split("\n"))
            yield CommentBlock(line, body.rstrip(), span, "comment")
            line += chunk.count("\n")
            i = end
            continue
        if c in "'\"":
            j = i + 1
            while j < n and text[j] != "\n" and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            prev_sig = c
            continue
        if c == "`":
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "`":
                    break
                if text[j] == "$" and j + 1 < n and text[j + 1] == "{":
                    template_depth.append(brace)
                    brace += 1
                    j += 2
                    break
                if text[j] == "\n":
                    line += 1
                j += 1
            i = j + 1
            prev_sig = "`"
            continue
        if c == "{":
            brace += 1
        elif c == "}":
            brace -= 1
            if template_depth and brace == template_depth[-1]:
                template_depth.pop()
                # Resume scanning the template literal text after the closing brace.
                j = i + 1
                while j < n:
                    if text[j] == "\\":
                        j += 2
                        continue
                    if text[j] == "`":
                        break
                    if text[j] == "$" and j + 1 < n and text[j + 1] == "{":
                        template_depth.append(brace)
                        brace += 1
                        j += 2
                        break
                    if text[j] == "\n":
                        line += 1
                    j += 1
                i = j + 1
                continue
        elif c == "/" and prev_sig in "(,=:[!&|?{};\n" or (c == "/" and prev_sig == ""):
            j = i + 1
            in_class = False
            while j < n and text[j] != "\n":
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "[":
                    in_class = True
                elif text[j] == "]":
                    in_class = False
                elif text[j] == "/" and not in_class:
                    break
                j += 1
            if j < n and text[j] == "/":
                i = j + 1
                prev_sig = "/"
                continue
        if not c.isspace():
            prev_sig = c
        i += 1
    yield from flush_run()


def hash_comments(text: str) -> Iterator[CommentBlock]:
    """
    Yields every `#` comment in shell, YAML, TOML, INI, Dockerfile or Caddyfile text.

    A whole-line comment, or a trailing comment after whitespace that follows an even number of quote
    characters, is a comment; a shebang is not. Consecutive whole-line comments form one block.

    Args:
        text: The file's contents.

    Yields:
        A CommentBlock per run of comment lines and per trailing comment.
    """
    run: list[tuple[int, str]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if stripped.startswith("#") and not (number == 1 and stripped.startswith("#!")):
            body = stripped.lstrip("#").strip()
            if run and run[-1][0] == number - 1:
                run.append((number, body))
            else:
                if run:
                    yield CommentBlock(run[0][0], "\n".join(t for _, t in run), len(run), "comment")
                run = [(number, body)]
            continue
        if run:
            yield CommentBlock(run[0][0], "\n".join(t for _, t in run), len(run), "comment")
            run = []
        m = re.search(r"\s#\s", raw)
        if m and raw[: m.start()].count('"') % 2 == 0 and raw[: m.start()].count("'") % 2 == 0:
            yield CommentBlock(number, raw[m.end() :].strip(), 1, "comment")
    if run:
        yield CommentBlock(run[0][0], "\n".join(t for _, t in run), len(run), "comment")


def comment_blocks(rel: str, text: str) -> Iterator[CommentBlock]:
    """
    Yields the comments and docstrings of one file, by its language.

    Args:
        rel: Repo-relative path (its suffix selects the scanner).
        text: The file's contents.

    Yields:
        Every CommentBlock the file holds.
    """
    suffix = Path(rel).suffix
    if suffix in PYTHON_SUFFIXES:
        yield from python_comments(text)
    elif suffix in C_STYLE_SUFFIXES:
        yield from c_style_comments(text)
    else:
        yield from hash_comments(text)


def check_text(rel: str, text: str, candidates: bool = False) -> list[str]:
    """
    Finds narrating comments in one file's text.

    Args:
        rel: Repo-relative path, used for the language and the messages.
        text: The file's contents.
        candidates: Also report over-long blocks and module docstrings (advisory).

    Returns:
        One "file:line: message" string per finding, in file order.
    """
    problems: list[str] = []
    for block in comment_blocks(rel, text):
        if EXEMPT_MARKER in block.text:
            continue
        block = CommentBlock(block.line, GENERATED_HEADER.sub("", block.text), block.lines, block.kind)
        for label, pattern in RULES:
            m = pattern.search(block.text)
            if m:
                before = block.text[: m.start()].count("\n")
                problems.append(f"{rel}:{block.line + before}: {label}: {m.group(0)!r}")
        if candidates:
            if block.kind == "module-docstring" and block.lines > MODULE_DOC_LIMIT:
                problems.append(f"{rel}:{block.line}: candidate: module docstring of {block.lines} lines")
            elif block.kind == "comment" and block.lines > BLOCK_LIMIT:
                problems.append(f"{rel}:{block.line}: candidate: comment block of {block.lines} lines")
            elif block.kind == "docstring" and block.lines > BLOCK_LIMIT * 4:
                problems.append(f"{rel}:{block.line}: candidate: docstring of {block.lines} lines")
    return problems


def check_file(rel: str, candidates: bool = False) -> list[str]:
    """
    Finds narrating comments in one tracked file.

    Args:
        rel: Repo-relative path.
        candidates: Also report over-long blocks (advisory).

    Returns:
        One message per finding; empty for an unreadable or missing file.
    """
    path = ROOT / rel
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    return check_text(rel, text, candidates)


def find_problems(only: list[str] | None = None, candidates: bool = False) -> list[str]:
    """
    Scans tracked source files.

    Args:
        only: Repo-relative paths to scan instead of every tracked file (read directly, without listing the
            repository); None scans everything.
        candidates: Also report over-long blocks (advisory).

    Returns:
        All findings, in file order.
    """
    if only is None:
        files = tracked_files()
    else:
        files = sorted({f for f in only if is_scanned(f)})
    problems: list[str] = []
    for rel in files:
        problems.extend(check_file(rel, candidates))
    return problems


def staged_files() -> list[str]:
    """Returns the added or modified staged paths."""
    out = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=AM"], cwd=ROOT, text=True
    )
    return out.splitlines()


def main(argv: list[str] | None = None) -> int:
    """
    CLI entry point.

    Args:
        argv: Command-line arguments (default `sys.argv[1:]`): `--staged` limits the scan to the staged files
            only (a commit never scans the rest of the repository; CI and the test scan everything),
            `--candidates` adds the advisory length items.

    Returns:
        0 when no comment narrates history (advisory items never fail), 1 otherwise.
    """
    args = sys.argv[1:] if argv is None else argv
    candidates = "--candidates" in args
    only = staged_files() if "--staged" in args else None
    problems = find_problems(only, candidates)
    failures = [p for p in problems if ": candidate: " not in p]
    for p in problems:
        print(p)
    if failures:
        print(f"\n{len(failures)} comment(s) narrate history or the conversation.", file=sys.stderr)
        return 1
    print("Every comment describes the code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
