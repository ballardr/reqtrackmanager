"""
Module: generate_long_text_inventory

Prints a table of every long free-text column of every table (a `Text` column, or a string of 1,000 characters or
more): whether its value is Markdown or plain text, its limit, and for a plain column the reason. For reading the
decisions at a glance (for example in a review); nothing is stored.

The declarations are the source (`ModuleDefinition.markdown_fields` / `plain_text_fields`, core ones in
`services.long_text_core`), and `backend/tests/test_long_text_inventory.py` fails for a column with none. Run it from
`backend/` with `PYTHONPATH=. python scripts/generate_long_text_inventory.py`.
"""

from sqlalchemy import String, Text

from app.database import Base
from app.modules.registry import get_plain_text_fields, import_all_module_models
from app.services.markdown_fields import declared_columns

#: A string column at least this long counts as long text; shorter ones are names, codes and addresses.
LONG_STRING_LENGTH = 1000


def long_text_columns() -> list[str]:
    """
    Every long free-text column.

    Returns:
        `table.column` names, sorted.
    """
    import_all_module_models()
    found = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            kind = column.type
            if isinstance(kind, Text) or (isinstance(kind, String) and (kind.length or 0) >= LONG_STRING_LENGTH):
                found.append(f"{table.name}.{column.name}")
    return sorted(found)


def render() -> str:
    """The inventory file's text."""
    markdown = declared_columns()
    plain = get_plain_text_fields()
    rows = []
    for key in long_text_columns():
        if key in markdown:
            field = markdown[key]
            note = "equations" if field.math else ""
            rows.append(f"| `{key}` | Markdown | {field.limit:,} | {note} |")
        else:
            rows.append(f"| `{key}` | Plain text | | {plain[key]} |")
    return (
        f"{len(markdown)} Markdown, {len(rows) - len(markdown)} plain text.\n\n"
        "| Column | Format | Limit (characters) | Note |\n|---|---|---|---|\n" + "\n".join(rows) + "\n"
    )


if __name__ == "__main__":
    print(render())
