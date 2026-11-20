#!/usr/bin/env python3
"""
Module: check_markdown_fields

Fails when a frontend long-text field is neither Markdown nor plain text with a stated reason, so a field added
later cannot be a third, undecided kind (docs/ux-style-guide.md, "Pattern: Markdown fields"; the stored columns are
declared on `ModuleDefinition.markdown_fields` and `plain_text_fields`). The baseline is empty.

Checks `frontend/src/**/*.tsx` (stories and tests excluded):
- a `<TextAreaField` must carry `markdown` (bare, `"simple"` or `"math"`) or `plainText="<reason>"`, and not both;
- an `<AutoGrowTextarea` outside the components that implement the editors (`AutoGrowTextarea.tsx`, `MarkdownEditor.tsx`,
  `FormFields.tsx`) must carry `plainText="<reason>"`; use `MarkdownEditor` for Markdown.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

IMPLEMENTATIONS = {"AutoGrowTextarea.tsx", "MarkdownEditor.tsx", "FormFields.tsx"}
TAGS = ("TextAreaField", "AutoGrowTextarea")
MARKDOWN = re.compile(r"""(?<![\w-])markdown(?![\w-])""")
PLAIN_REASON = re.compile(r"""(?<![\w-])plainText=(?:"[^"\s][^"]*"|'[^'\s][^']*'|\{\s*(?:"[^"\s][^"]*"|'[^'\s][^']*')\s*\})""")
PLAIN_ANY = re.compile(r"""(?<![\w-])plainText(?![\w-])""")


def elements(text: str, tag: str) -> list[tuple[int, str]]:
    """
    The JSX elements named `tag` in `text`.

    Args:
        text: A TSX source.
        tag: The component name (`TextAreaField`).

    Returns:
        `(line number, element source)` for each opening tag, read up to its closing `>` or `/>` outside braces and strings.
    """
    found = []
    for match in re.finditer(rf"<{tag}(?![\w.-])", text):
        depth, quote, index = 0, None, match.end()
        while index < len(text):
            char = text[index]
            if quote:
                if char == "\\":
                    index += 1
                elif char == quote:
                    quote = None
            elif char in "\"'`":
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            elif char == ">" and depth == 0:
                break
            index += 1
        found.append((text.count("\n", 0, match.start()) + 1, text[match.start():index + 1]))
    return found


def violations() -> list[str]:
    """Returns `path:line: message` for every long-text field that is not Markdown and gives no reason."""
    found = []
    for path in sorted(SRC.rglob("*.tsx")):
        if path.name.endswith((".stories.tsx", ".test.tsx")):
            continue
        text = path.read_text(encoding="utf-8")
        for tag in TAGS:
            if tag == "AutoGrowTextarea" and path.name in IMPLEMENTATIONS:
                continue
            for number, element in elements(text, tag):
                where = f"{path.relative_to(SRC).as_posix()}:{number}"
                is_markdown = bool(MARKDOWN.search(element)) and tag == "TextAreaField"
                has_reason = bool(PLAIN_REASON.search(element))
                if PLAIN_ANY.search(element) and not has_reason:
                    found.append(f"{where}: plainText needs a reason, e.g. plainText=\"a one-line label\".")
                elif is_markdown and has_reason:
                    found.append(f"{where}: a field is Markdown or plain text, not both.")
                elif not is_markdown and not has_reason:
                    hint = "markdown" if tag == "TextAreaField" else "MarkdownEditor, or plainText=\"<reason>\""
                    found.append(f"{where}: <{tag}> must be Markdown (use {hint}) or plainText with a reason.")
    return found


def main() -> int:
    """Prints each offending element and exits 1 when there is any."""
    found = violations()
    for item in found:
        print(item)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
