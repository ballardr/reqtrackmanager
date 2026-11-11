"""Static reachability of an audit write from a route handler (used by `test_mutating_routes_audited.py`).

A name is resolved the way Python resolves it (a reference counts as well as a call): a function defined in the
same module, a name imported from another `app` module, or an attribute of an imported `app` module. Calls it
cannot resolve (methods on objects) are ignored, so a handler is reported only when no path of resolvable calls
reaches `log_event`, `log_login` or a helper that wraps them.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
AUDIT_WRITERS = {"log_event", "log_login", "audit_comment"}


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(APP.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


@lru_cache(maxsize=1)
def _index() -> tuple[dict[tuple[str, str], list[tuple[str, str] | str]], set[str]]:
    """`{(module, function): [resolved callee or bare name]}` and the set of modules."""
    functions: dict[tuple[str, str], list[tuple[str, str] | str]] = {}
    modules: set[str] = set()
    for path in APP.rglob("*.py"):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        module = _module_name(path)
        modules.add(module)
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        names: dict[str, tuple[str, str]] = {}   # imported name -> (module, name)
        aliases: dict[str, str] = {}              # alias -> module
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app"):
                for alias in node.names:
                    names[alias.asname or alias.name] = (node.module, alias.name)
                    aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app"):
                        aliases[alias.asname or alias.name.split(".")[0]] = alias.name
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            callees: list[tuple[str, str] | str] = []
            for ref in ast.walk(node):
                # Every reference counts, not only a call: a handler often hands a function to a thread pool.
                if isinstance(ref, ast.Name):
                    if ref.id in AUDIT_WRITERS:
                        callees.append(ref.id)
                    elif ref.id in names:
                        callees.append(names[ref.id])
                    else:
                        callees.append((module, ref.id))
                elif isinstance(ref, ast.Attribute):
                    if ref.attr in AUDIT_WRITERS:
                        callees.append(ref.attr)
                    elif isinstance(ref.value, ast.Name) and ref.value.id in aliases:
                        callees.append((aliases[ref.value.id], ref.attr))
            functions.setdefault((module, node.name), []).extend(callees)
    return functions, modules


def reaches_audit(module: str, function: str) -> bool:
    """Whether `function` in `module` can reach an audit write through calls that resolve to `app` code."""
    functions, _ = _index()
    seen: set[tuple[str, str]] = set()
    stack = [(module, function)]
    while stack:
        key = stack.pop()
        if key in seen:
            continue
        seen.add(key)
        for callee in functions.get(key, []):
            if isinstance(callee, str):
                return True
            stack.append(callee)
    return False
