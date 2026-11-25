"""
Module: tests.test_changed_tests

Pins `scripts/changed_tests.py`, which names the test files a pull request changes so CI repeats them: the stories
and backend tests it adds or edits, the story beside a changed component, and nothing deleted or unrelated.

Skipped when the repository root is not visible (the backend container mounts only backend/).
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "changed_tests.py"
pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="repository checkout not available")


def _module():
    spec = importlib.util.spec_from_file_location("changed_tests", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _touch(root: Path, *paths: str) -> None:
    for path in paths:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")


def test_a_changed_component_repeats_the_story_beside_it(tmp_path):
    _touch(tmp_path, "frontend/src/components/Box.tsx", "frontend/src/components/Box.stories.tsx",
           "frontend/src/components/Lone.tsx", "frontend/src/hooks/useThing.ts", "frontend/src/hooks/useThing.stories.tsx")
    changed = ["frontend/src/components/Box.tsx", "frontend/src/components/Lone.tsx", "frontend/src/hooks/useThing.ts",
               "frontend/src/styles/theme.css", "README.md"]
    assert _module().frontend_stories(changed, tmp_path) == [
        "src/components/Box.stories.tsx", "src/hooks/useThing.stories.tsx",
    ]


def test_a_changed_story_is_repeated_once_even_with_its_component(tmp_path):
    _touch(tmp_path, "frontend/src/components/Box.tsx", "frontend/src/components/Box.stories.tsx")
    changed = ["frontend/src/components/Box.stories.tsx", "frontend/src/components/Box.tsx"]
    assert _module().frontend_stories(changed, tmp_path) == ["src/components/Box.stories.tsx"]


def test_only_existing_backend_test_files_are_repeated(tmp_path):
    _touch(tmp_path, "backend/tests/test_a.py", "backend/app/modules/m/tests/test_b.py", "backend/app/service.py",
           "backend/tests/conftest.py")
    changed = ["backend/tests/test_a.py", "backend/app/modules/m/tests/test_b.py", "backend/app/service.py",
               "backend/tests/conftest.py", "backend/tests/test_gone.py", "scripts/test_not_backend.py"]
    assert _module().backend_tests(changed, tmp_path) == ["app/modules/m/tests/test_b.py", "tests/test_a.py"]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=root, check=True,
                   capture_output=True)


def test_the_diff_against_the_base_lists_added_and_modified_files_only(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _touch(tmp_path, "backend/tests/test_old.py", "backend/tests/test_removed.py")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    (tmp_path / "backend/tests/test_old.py").write_text("changed")
    (tmp_path / "backend/tests/test_removed.py").unlink()
    _touch(tmp_path, "backend/tests/test_new.py")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "change")
    assert _module().changed_files("main", tmp_path) == ["backend/tests/test_new.py", "backend/tests/test_old.py"]
