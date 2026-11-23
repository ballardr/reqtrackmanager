"""
Module: conftest (rootdir)

Registers `tests/conftest.py` as a pytest plugin so its fixtures (`client`, `admin_token`, `org_id`, the session-scoped
`_schema` setup) also apply to tests outside `tests/`, such as a module's colocated test directory
(`app/modules/compliance/tests/`).

Design decisions:
- `pytest_plugins` may only be declared in a rootdir-level conftest, which is why this file exists at `backend/`.
- `tests/conftest.py` stays where it is because dozens of test files import it by dotted path
  (`from tests.conftest import ...`); this file only adds a second route to its fixtures.
- It holds the `--shuffle-seed` option, which must be registered exactly once (`tests/conftest.py` is loaded both as this
  plugin and as the tests directory's own conftest).
"""

import random

pytest_plugins = ["tests.conftest"]


def pytest_addoption(parser):
    """Adds `--shuffle-seed N`: runs the tests in a random order fixed by N (the same on every xdist worker)."""
    parser.addoption("--shuffle-seed", type=int, default=None, help="shuffle the test order with this seed")


def pytest_collection_modifyitems(config, items):
    """Shuffles the collected tests when `--shuffle-seed` is given, to show that no test depends on running after another.

    Each xdist worker collects the same list and shuffles it with the same seed, so they still agree on the order, which
    xdist requires.
    """
    seed = config.getoption("--shuffle-seed")
    if seed is not None:
        random.Random(seed).shuffle(items)
