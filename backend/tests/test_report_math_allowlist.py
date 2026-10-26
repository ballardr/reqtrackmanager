"""The screen and the reports must accept the same TeX: the frontend reads the allow-list from a generated file and
shares test vectors with the backend. No database."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.services.report_math import tex_problem

FRONTEND_UTILS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils"
CASES = json.loads((FRONTEND_UTILS / "mathTexCases.json").read_text(encoding="utf-8"))


def _generator():
    script = Path(__file__).resolve().parents[1] / "scripts" / "generate_math_allowlist.py"
    spec = importlib.util.spec_from_file_location("generate_math_allowlist", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_frontend_allow_list_file_is_what_the_backend_defines():
    generator = _generator()

    assert generator.TARGET.read_text(encoding="utf-8") == generator.render(), (
        "frontend/src/utils/mathAllowList.json is out of date: run `python scripts/generate_math_allowlist.py` in backend/"
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: repr(c["tex"])[:40])
def test_the_shared_vectors_agree_with_the_backend_check(case):
    assert (tex_problem(case["tex"]) is None) is case["ok"]
