"""
Module: generate_math_allowlist

Writes `frontend/src/utils/mathAllowList.json` from `app.services.report_math`, the one definition of which TeX a
report may contain, so the screen's check (`frontend/src/utils/mathTex.ts`) uses the same list.

`backend/tests/test_report_math_allowlist.py` fails when the file differs from what this script writes; run it
from `backend/` (`python scripts/generate_math_allowlist.py`) after changing the allow-list.
"""

import json
from pathlib import Path

from app.services import report_math

TARGET = Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils" / "mathAllowList.json"


def allow_list() -> dict[str, object]:
    """The allow-list as plain data: what `tex_problem` consults, sorted so the file is stable."""
    return {
        "commands": sorted(report_math.ALLOWED_COMMANDS),
        "symbolCommands": sorted(report_math.ALLOWED_SYMBOL_COMMANDS),
        "environments": sorted(report_math.ALLOWED_ENVIRONMENTS),
        "textCommands": sorted(report_math.TEXT_COMMANDS),
        "forbiddenCharacters": "".join(sorted(report_math.FORBIDDEN_CHARACTERS)),
        "plainTextPattern": report_math.PLAIN_TEXT.pattern,
        "maxChars": report_math.MAX_TEX_CHARS,
        "maxDepth": report_math.MAX_TEX_DEPTH,
    }


def render() -> str:
    """The file's text."""
    return json.dumps(allow_list(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    TARGET.write_text(render(), encoding="utf-8")
    print(f"wrote {TARGET}")
