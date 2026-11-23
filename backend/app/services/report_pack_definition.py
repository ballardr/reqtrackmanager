"""
Module: services.report_pack_definition

The definition a report pack is stored in, and its validation.

Responsibilities:
- The vocabulary: `schema_version`, optional `variables` (declared as a layout's, `report_variables`), optional
  `file_name` (a `{{placeholder}}` template, `report_file_names`) and `entries` (at most `MAX_ENTRIES`).
- A layout entry `{"kind": "layout", "name", "tier"?, "format", "filename"?, "variables"?}` names its layout, never by id,
  so a pack is portable; `tier` pins which owner's layout is meant, else the nearest. A module report entry
  `{"kind": "report", "module_key", "report", "format", "filename"?, "params"?}`.
- `validate_definition` / `assert_valid` (every problem listed), `definition_hash` (SHA-256 of canonical JSON).

Design decisions:
- A layout entry receives the pack variable of the same name, type and list-ness, or the value it fixes itself,
  resolved when the pack runs (a layout's variables are unknown at save time).
- Checks needing the registry happen here; checks needing a layout happen at run, so a layout that is missing or does
  not offer the format makes that entry "not available" in the manifest instead of making the pack unsavable.
- Fixed values and filenames are configuration, never parsed as expressions.

Dependencies: `report_layout_tree`, `report_variables`, `report_widgets`, `report_render`.
"""

from __future__ import annotations

import json
from typing import Any

from app.modules.registry import get_all_reports
from app.services.report_file_names import clean_filename, template_problems
from app.services.report_framework import REPORT_FORMATS as framework_formats
from app.services.report_layout_tree import TreeError, TreeValidator, tree_hash
from app.services.report_render import formats_for
from app.services.report_variables import MAX_LIST_VALUES, MAX_VALUE_CHARS, NAME_RE
from app.services.report_widgets import param_value_problem

PACK_SCHEMA_VERSION = 1
MAX_ENTRIES = 25
MAX_FILENAME_CHARS = 60
MAX_DEFINITION_BYTES = 256_000
MAX_ERRORS = 50
#: The formats a module report can be produced in as a pack entry: every file format the framework offers.
REPORT_FORMATS = tuple(f for f in framework_formats if f != "json")
LAYOUT_TIERS = ("organization", "project")


class InvalidPackError(ValueError):
    """A definition failed validation; `errors` lists every problem found."""

    def __init__(self, errors: list[TreeError]) -> None:
        self.errors = errors
        super().__init__("; ".join(f"{e.path}: {e.message}" for e in errors[:5]) or "invalid pack")


def layout_formats() -> list[str]:
    """Every format any layout family can be produced in (an entry's format is checked against its layout at run)."""
    return sorted({*formats_for("document"), *formats_for("table")})


def definition_hash(definition: dict[str, Any]) -> str:
    """SHA-256 hex of the definition's canonical JSON (the same method as a layout tree)."""
    return tree_hash(definition)


def empty_definition() -> dict[str, Any]:
    """A valid definition with no entries (not yet runnable, but savable as a draft)."""
    return {"schema_version": PACK_SCHEMA_VERSION, "entries": []}


def _value_shape_problem(value: Any) -> str | None:
    """Why `value` cannot be a fixed variable value (a scalar, or a short list of scalars)."""
    def scalar_ok(item: Any) -> bool:
        if isinstance(item, bool) or isinstance(item, int | float):
            return True
        return isinstance(item, str) and 0 < len(item) <= MAX_VALUE_CHARS

    if isinstance(value, list):
        if not 0 < len(value) <= MAX_LIST_VALUES or not all(scalar_ok(i) for i in value):
            return f"Must be 1 to {MAX_LIST_VALUES} values, each text (up to {MAX_VALUE_CHARS} characters), number or yes/no."
        return None
    return None if scalar_ok(value) else f"Must be text (up to {MAX_VALUE_CHARS} characters), a number, yes/no, or a list of those."


class _PackValidator:
    """Collects errors for one definition (reusing the layout validator's variable declaration checks)."""

    def __init__(self) -> None:
        self.tree = TreeValidator()

    def error(self, path: str, message: str) -> None:
        """Records a problem (dropped past `MAX_ERRORS`)."""
        if len(self.tree.analysis.errors) < MAX_ERRORS:
            self.tree.analysis.errors.append(TreeError(path, message))

    def run(self, definition: Any) -> list[TreeError]:
        """Validates `definition`; returns the problems (empty when it may be saved)."""
        if not isinstance(definition, dict):
            self.error("", "The pack must be an object.")
            return self.tree.analysis.errors
        try:
            size = len(json.dumps(definition, ensure_ascii=False))
        except (TypeError, ValueError):
            self.error("", "The pack must be plain JSON.")
            return self.tree.analysis.errors
        if size > MAX_DEFINITION_BYTES:
            self.error("", f"The pack is too large ({size} bytes; the limit is {MAX_DEFINITION_BYTES}).")
            return self.tree.analysis.errors
        self.tree.check_keys(definition, "", required=("schema_version", "entries"), optional=("variables", "file_name"))
        if definition.get("schema_version") != PACK_SCHEMA_VERSION:
            self.error("schema_version", f"Must be {PACK_SCHEMA_VERSION}.")
        if "variables" in definition:
            self.tree.variable_declarations(definition["variables"], "variables")
        if "file_name" in definition:
            declared = definition.get("variables")
            names = [d["name"] for d in declared if isinstance(d, dict) and isinstance(d.get("name"), str)] if isinstance(declared, list) else []
            for problem in template_problems(definition["file_name"], variables=names):
                self.error("file_name", problem)
        entries = definition.get("entries")
        if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
            if "entries" in definition:
                self.error("entries", f"Must be a list of at most {MAX_ENTRIES} reports.")
        else:
            for index, entry in enumerate(entries):
                self._entry(entry, f"entries[{index}]")
        return self.tree.analysis.errors

    def _entry(self, entry: Any, path: str) -> None:
        if not isinstance(entry, dict):
            self.error(path, "Must be an object.")
            return
        kind = entry.get("kind")
        if kind == "layout":
            self.tree.check_keys(entry, path, required=("kind", "name", "format"), optional=("tier", "filename", "variables"))
            if "name" in entry:
                self.tree.text(entry["name"], f"{path}.name", limit=200)
            if "tier" in entry and entry["tier"] not in LAYOUT_TIERS:
                self.error(f"{path}.tier", f"Must be one of: {', '.join(LAYOUT_TIERS)}.")
            allowed = layout_formats()
            if entry.get("format") not in allowed:
                self.error(f"{path}.format", f"Must be one of: {', '.join(allowed)}.")
            if "variables" in entry:
                self._fixed_values(entry["variables"], f"{path}.variables")
        elif kind == "report":
            self.tree.check_keys(entry, path, required=("kind", "module_key", "report", "format"), optional=("filename", "params"))
            if entry.get("format") not in REPORT_FORMATS:
                self.error(f"{path}.format", f"Must be one of: {', '.join(REPORT_FORMATS)}.")
            definition = self._report_definition(entry, path)
            if definition is not None and "params" in entry:
                self._report_params(definition.params, entry["params"], f"{path}.params")
        else:
            self.error(f"{path}.kind", 'Must be "layout" or "report".')
            return
        if "filename" in entry:
            for problem in template_problems(entry["filename"], any_variable=True):
                self.error(f"{path}.filename", problem)

    def _report_definition(self, entry: dict[str, Any], path: str) -> Any:
        """The module report an entry names, or `None` (with an error)."""
        module_key, key = entry.get("module_key"), entry.get("report")
        for mk, definition in get_all_reports():
            if mk == module_key and definition.key == key:
                return definition
        self.error(f"{path}.report", f"No report {key!r} of module {module_key!r} is installed.")
        return None

    def _report_params(self, declared: Any, params: Any, path: str) -> None:
        if not isinstance(params, dict) or not params:
            self.error(path, "Leave params out when no parameter is set.")
            return
        by_name = {p.name: p for p in declared}
        for name, value in params.items():
            param = by_name.get(name)
            if param is None:
                known = ", ".join(by_name) or "none"
                self.error(f"{path}.{name}", f"This report has no parameter {name!r}. Its parameters: {known}.")
                continue
            problem = param_value_problem(param, value)
            if problem:
                self.error(f"{path}.{name}", problem)

    def _fixed_values(self, values: Any, path: str) -> None:
        if not isinstance(values, dict) or not values or len(values) > 20:
            self.error(path, "Leave variables out when none is fixed; otherwise an object of up to 20 values.")
            return
        for name, value in values.items():
            if not isinstance(name, str) or not NAME_RE.match(name):
                self.error(f"{path}.{name}", "Not a variable name.")
                continue
            problem = _value_shape_problem(value)
            if problem:
                self.error(f"{path}.{name}", problem)


def validate_definition(definition: Any) -> list[TreeError]:
    """The problems with `definition` (empty when it may be stored)."""
    return _PackValidator().run(definition)


def assert_valid(definition: Any) -> None:
    """`validate_definition`, raising when invalid.

    Raises:
        InvalidPackError: With every problem found.
    """
    errors = validate_definition(definition)
    if errors:
        raise InvalidPackError(errors)


__all__ = [
    "LAYOUT_TIERS", "MAX_ENTRIES", "MAX_FILENAME_CHARS", "PACK_SCHEMA_VERSION", "REPORT_FORMATS", "InvalidPackError",
    "assert_valid", "clean_filename", "definition_hash", "empty_definition", "layout_formats", "validate_definition",
]
