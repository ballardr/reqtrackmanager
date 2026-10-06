"""Guard that keeps the frontend's artefact-type route check honest.

`frontend/src/modules/artefactPaths.stories.tsx` asserts every artefact type in
`frontend/src/modules/registeredArtefactTypes.json` resolves to a page, so a type
can never be linkable yet unreachable. That file must therefore equal the backend
registry; this test fails, naming the difference, when a module registers (or
drops) an artefact type without the file being updated. The frontend is not part
of the backend image, so the test is skipped there.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.registry import get_all_registered_artefact_types

FIXTURE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "modules" / "registeredArtefactTypes.json"


@pytest.mark.skipif(not FIXTURE.exists(), reason="frontend sources are not available (backend-only image)")
def test_frontend_route_fixture_matches_the_backend_artefact_type_registry():
    listed = set(json.loads(FIXTURE.read_text()))
    registered = get_all_registered_artefact_types()
    assert listed == registered, (
        f"frontend/src/modules/registeredArtefactTypes.json is out of date. Missing: {sorted(registered - listed)}; "
        f"stale: {sorted(listed - registered)}. Update the file, and give any new type a page via its module's "
        "`artefactPaths` (frontend/src/modules/<key>/module.ts) so it is reachable from a link."
    )
