"""
Module: conftest (rootdir)

Registers `tests/conftest.py` as a pytest plugin, so its fixtures (`client`,
`admin_token`, `org_id`, the session-scoped `_schema`/migration setup, etc.)
apply to test files living *outside* the `tests/` directory tree too — most
notably each first-party module's own colocated test directory (e.g.
`app/modules/compliance/tests/`, a
follow-up: that module's tests moved out of the flat, shared `tests/`
directory to live alongside the rest of its own code).

pytest applies a conftest.py's fixtures automatically to its own directory
and everything *below* it — but `app/modules/compliance/tests/` is not
below `tests/`, it's a sibling subtree entirely, so `tests/conftest.py`'s
own fixture-cascade would never reach it on its own. `pytest_plugins` is
pytest's own supported mechanism for pulling in another conftest's fixtures
regardless of directory relationship — but it may only be declared in a
*rootdir*-level conftest.py (a restriction pytest enforces; declaring it in
a nested one is deprecated/rejected), which is exactly why this tiny file
exists at `backend/` itself (this project's own pytest rootdir, confirmed
by `backend/pyproject.toml`'s presence) rather than being folded into
`tests/conftest.py` in place.

Deliberately does not *move* `tests/conftest.py`'s own content here: that
file is imported by dotted path (`from tests.conftest import auth_headers,
...`) throughout dozens of existing test files across this suite, and
relocating it would break every one of those imports for no benefit — this
file only adds a second way to *reach* those same fixtures from outside
`tests/`'s own directory tree, without changing where the real
implementation lives.

It also holds the `--shuffle-seed` option, which has to be registered exactly once (`tests/conftest.py` is loaded both
as this plugin and as the tests directory's own conftest, so an option added there would be registered twice).
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
