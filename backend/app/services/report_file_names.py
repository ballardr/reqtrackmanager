"""
Module: services.report_file_names

Default output file names for generated reports: the `{{placeholder}}` template a layout, a pack, a pack entry or an
organisation can set, its check at save time and the safe file stem it produces.

Responsibilities:
- Define which placeholders a file name may use (`FILE_NAME_PLACEHOLDERS`, `ORG_FILE_NAME_PLACEHOLDERS`).
- `template_problems`: why a template cannot be saved (an unknown name, a record field, an unknown variable).
- `render_stem`: the template filled in and reduced to a flat, safe stem, or `None` when nothing usable is left, so
  the caller falls back to the name it always used.
- `clean_filename`: the one sanitiser for a name made from user text (packs, entries, templates).
- `sample_values`: the values the designer's live example uses.

Design decisions:
- **A file name, never a path.** The stem is reduced to letters, digits, space, dot, dash and underscore; accents are
  folded to their base letter; separators, `..`, control characters (so CR and LF), quotes and non-ASCII are removed
  or replaced; leading and trailing dots, spaces and dashes go; Windows device names are prefixed; the length is
  capped. The extension is chosen by the renderer, never by the template, and no value reaches a response header
  except through `services.downloads.file_response`, which encodes it.
- **Values are cleaned one by one before they are joined** and cut to `MAX_VALUE_CHARS`, so a long project
  description or a long list cannot crowd out the rest of the name, and a hostile value (`../x`, a line break) has
  already lost its structure when the whole name is cleaned again.
- **One placeholder syntax.** The pattern is the report text's own (`services.report_model.PLACEHOLDER_RE`) and the
  values come from the same run facts the document's placeholders use, so a name cannot drift from the document.
  Record fields are not available (a file has no current record); the record-image name rule is the place for them.
- **Never fails a run.** An empty template or an empty result falls back; an unknown name at render time is empty.

Dependencies: `services.report_model`, `services.report_variables` (the `var` family name).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Mapping
from typing import Any

from app.services.client_date import effective_today
from app.services.report_model import PLACEHOLDER_RE
from app.services.report_variables import PLACEHOLDER_FAMILY

#: Longest template an author may save.
MAX_TEMPLATE_CHARS = 200
#: Longest stem a template produces (the extension is added to it).
MAX_STEM_CHARS = 100
#: Longest one substituted value, so a long list or title cannot crowd out the rest of the name.
MAX_VALUE_CHARS = 40
#: Placeholders a layout, a pack or a pack entry may use: the run facts, plus `{{var.name}}`.
FILE_NAME_PLACEHOLDERS: tuple[str, ...] = (
    "report_title", "project_name", "project_code", "organisation", "generated_on", "layout_version", "format",
)
#: Placeholders the organisation's default may use: no layout version and no variables, since it names every report.
ORG_FILE_NAME_PLACEHOLDERS: tuple[str, ...] = (
    "report_title", "project_name", "project_code", "organisation", "generated_on", "format",
)
_BAD = re.compile(r"[^A-Za-z0-9 ._-]")
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.IGNORECASE)


def clean_filename(name: str, *, limit: int = 60) -> str:
    """`name` reduced to a flat, safe file stem (see the module docstring).

    Args:
        name: Text from a user, a record or a variable.
        limit: Longest result.

    Returns:
        The stem; `report` when nothing usable is left. A path separator or `..` can never survive.
    """
    return _clean(name, limit) or "report"


def _clean(name: str, limit: int) -> str:
    """`clean_filename` without the fallback: empty when nothing usable is left."""
    folded = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in folded if not unicodedata.combining(c))
    cleaned = re.sub(r"-{2,}", "-", _BAD.sub("-", ascii_only)).strip(" .-")
    cleaned = re.sub(r"\.{2,}", ".", cleaned)[:limit].strip(" .-")
    return f"_{cleaned}" if _RESERVED.match(cleaned) else cleaned


def template_problems(
    template: object, *, allowed: Collection[str] = FILE_NAME_PLACEHOLDERS, variables: Collection[str] | None = (),
    any_variable: bool = False,
) -> list[str]:
    """Why `template` cannot be saved as a file name, in the words shown beside the field.

    Args:
        template: The value to check (must be text).
        allowed: The plain placeholder names that are valid here.
        variables: The run-time variables `{{var.name}}` may name; `None` means the place has no variables.
        any_variable: Accept any well-formed `{{var.name}}` (a pack entry's layout is only known when it runs).

    Returns:
        The problems, empty when the template is acceptable.
    """
    if not isinstance(template, str):
        return ["Must be text."]
    problems: list[str] = []
    if not template.strip():
        return ["Write a name, or leave it out."]
    if len(template) > MAX_TEMPLATE_CHARS:
        problems.append(f"At most {MAX_TEMPLATE_CHARS} characters.")
    seen: set[str] = set()
    for match in PLACEHOLDER_RE.finditer(template):
        name, member = match.group(1), match.group(2)
        label = f"{{{{{name}.{member}}}}}" if member else f"{{{{{name}}}}}"
        if label in seen:
            continue
        seen.add(label)
        if member is None:
            if name not in allowed:
                problems.append(f'Unknown placeholder "{label}". Use: {", ".join(f"{{{{{n}}}}}" for n in allowed)}.')
        elif name != PLACEHOLDER_FAMILY:
            problems.append(f'"{label}" names a record field, but a file has no current record. Use {{{{var.name}}}} for a variable.')
        elif variables is None:
            problems.append(f'"{label}" is a variable, which this name cannot use.')
        elif not any_variable and member not in variables:
            problems.append(f'"{member}" is not a variable of this layout. Variables: {", ".join(variables) or "none"}.')
    return problems


def render_stem(
    template: str | None, values: Mapping[str, str], variable_text: Mapping[str, str] | None = None,
) -> str | None:
    """The file stem a template produces, or `None` when the caller should use its usual name.

    Args:
        template: The author's template; `None` or blank means none.
        values: Plain placeholder values by name (`report_title`, `project_code` ...). A name not given is empty.
        variable_text: `{{var.name}}` values as printed text (a list already joined).

    Returns:
        The cleaned stem (never a path, at most `MAX_STEM_CHARS`), or `None` when the template is empty or fills in to
        nothing usable.
    """
    if not template or not template.strip():
        return None
    variable_text = variable_text or {}

    def substitute(match: re.Match[str]) -> str:
        name, member = match.group(1), match.group(2)
        raw = variable_text.get(member, "") if member is not None and name == PLACEHOLDER_FAMILY else values.get(name, "") if member is None else ""
        return _clean(raw, MAX_VALUE_CHARS)

    return _clean(PLACEHOLDER_RE.sub(substitute, template), MAX_STEM_CHARS) or None


def org_default_stem(
    organization: Any, project: Any | None, *, title: str, extension: str, fallback: str,
) -> str:
    """The stem of a report that has no template of its own: the organisation's default, else `fallback`.

    Args:
        organization: The organisation (`report_file_name`, `name`).
        project: The project reported on, or `None` for an organisation-wide report.
        title: The report's title, for `{{report_title}}`.
        extension: The produced file's extension, for `{{format}}`.
        fallback: The name used when the organisation sets none or its template fills in to nothing.

    Returns:
        A flat, safe stem. `{{generated_on}}` is the caller's own calendar day.
    """
    plain = {
        "report_title": title, "project_name": project.name if project is not None else organization.name,
        "organisation": organization.name, "project_code": (project.code if project is not None else "") or "",
        "generated_on": effective_today().isoformat(), "format": extension,
    }
    return render_stem(organization.report_file_name, plain) or fallback


#: Where a template is set; decides which placeholders it may use.
KIND_LAYOUT = "layout"
KIND_PACK = "pack"
KIND_ENTRY = "entry"
KIND_ORGANIZATION = "organization"
KINDS = (KIND_LAYOUT, KIND_PACK, KIND_ENTRY, KIND_ORGANIZATION)


def allowed_placeholders(kind: str, variables: Collection[str] = ()) -> list[str]:
    """The `{{...}}` texts a template of `kind` may use, for the designer's insert list.

    Args:
        kind: One of `KINDS`.
        variables: The run-time variables the place declares (an organisation default has none).

    Returns:
        The plain placeholders, then one `{{var.name}}` per variable.
    """
    organization = kind == KIND_ORGANIZATION
    names = ORG_FILE_NAME_PLACEHOLDERS if organization else FILE_NAME_PLACEHOLDERS
    return [*(f"{{{{{n}}}}}" for n in names), *([] if organization else [f"{{{{var.{v}}}}}" for v in variables])]


def example(
    template: str, *, kind: str, variables: Collection[str] = (), extension: str = "pdf",
) -> tuple[str | None, list[str]]:
    """The designer's live example: the name the template would give, with sample values, and its problems.

    Args:
        template: The author's template.
        kind: One of `KINDS`.
        variables: The names of the run-time variables the place declares (a layout's or a pack's).
        extension: The extension to show and use for `{{format}}`.

    Returns:
        `(file name with extension or None when the template is empty or has problems, problems)`. Nothing from a real
        project is used, so the endpoint is safe for any signed-in person.
    """
    organization = kind == KIND_ORGANIZATION
    problems = template_problems(
        template, allowed=ORG_FILE_NAME_PLACEHOLDERS if organization else FILE_NAME_PLACEHOLDERS,
        variables=None if organization else variables, any_variable=kind == KIND_ENTRY,
    )
    if problems:
        return None, problems
    plain = sample_values(format_name=extension)
    stem = render_stem(template, plain, {name: f"{name.title()} value" for name in variables})
    return (f"{stem}.{extension}" if stem else None), []


def sample_values(*, format_name: str = "pdf") -> dict[str, str]:
    """Example values for the designer's live example (nothing from a real project)."""
    return {
        "report_title": "Quarterly review", "project_name": "Apollo", "project_code": "ACME", "organisation": "Acme Ltd",
        "generated_on": "2026-10-29", "layout_version": "3", "format": format_name,
    }


__all__ = [
    "FILE_NAME_PLACEHOLDERS", "KINDS", "KIND_ENTRY", "KIND_LAYOUT", "KIND_ORGANIZATION", "KIND_PACK", "MAX_STEM_CHARS",
    "MAX_TEMPLATE_CHARS", "MAX_VALUE_CHARS", "ORG_FILE_NAME_PLACEHOLDERS", "allowed_placeholders", "clean_filename", "example", "org_default_stem",
    "render_stem", "sample_values", "template_problems",
]
